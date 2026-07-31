import json
import sqlite3
import asyncio
import urllib.request
import urllib.error
from contextlib import contextmanager
from datetime import datetime, timedelta
from config import DB_PATH, TURSO_URL, TURSO_TOKEN


# ── Turso HTTP API ─────────────────────────────────────────────────────────────

def _turso_http_url():
    url = TURSO_URL
    if url.startswith("libsql://"):
        url = "https://" + url[9:]
    return url


def _to_arg(v):
    if v is None:
        return {"type": "null", "value": None}
    if isinstance(v, bool):
        return {"type": "integer", "value": "1" if v else "0"}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "real", "value": str(v)}
    return {"type": "text", "value": str(v)}


def _from_cell(cell):
    typ = cell.get("type")
    val = cell.get("value")
    if typ == "null" or val is None:
        return None
    if typ == "integer":
        return int(val)
    if typ == "real":
        return float(val)
    return val


def _turso_exec(sql, params=()):
    """Execute one SQL statement via Turso HTTP API. Returns (cols, rows)."""
    stmt = {"sql": sql}
    if params:
        stmt["args"] = [_to_arg(v) for v in params]

    body = json.dumps({
        "requests": [
            {"type": "execute", "stmt": stmt},
            {"type": "close"},
        ]
    }).encode()

    req = urllib.request.Request(
        f"{_turso_http_url()}/v2/pipeline",
        data=body,
        headers={
            "Authorization": f"Bearer {TURSO_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Turso HTTP {e.code}: {e.read().decode()}") from e

    results = data.get("results", [])
    if results and results[0].get("type") == "error":
        raise RuntimeError(f"Turso SQL error: {results[0].get('error')}")
    if not results or results[0].get("type") != "ok":
        return [], []

    res = results[0].get("response", {}).get("result", {})
    cols = [c["name"] for c in res.get("cols", [])]
    rows = [[_from_cell(cell) for cell in raw] for raw in res.get("rows", [])]
    return cols, rows


class _TursoCursor:
    def __init__(self, cols, rows, as_dicts=False):
        self._cols = cols
        self._rows = rows
        self._as_dicts = as_dicts
        self._idx = 0

    def _wrap(self, row):
        return dict(zip(self._cols, row)) if self._as_dicts else row

    def fetchone(self):
        if self._idx >= len(self._rows):
            return None
        r = self._rows[self._idx]
        self._idx += 1
        return self._wrap(r)

    def fetchall(self):
        rows = [self._wrap(r) for r in self._rows[self._idx:]]
        self._idx = len(self._rows)
        return rows


class _TursoConn:
    """Mimics sqlite3.Connection using Turso HTTP API."""
    row_factory = None

    def execute(self, sql, params=()):
        cols, rows = _turso_exec(sql, params)
        return _TursoCursor(cols, rows, as_dicts=(self.row_factory is not None))

    def commit(self):
        pass  # HTTP API is auto-commit

    def rollback(self):
        pass

    def close(self):
        pass


# ── Connection factory ─────────────────────────────────────────────────────────

@contextmanager
def _db():
    if TURSO_URL and TURSO_TOKEN:
        conn = _TursoConn()
        try:
            yield conn
        finally:
            pass
    else:
        conn = sqlite3.connect(str(DB_PATH))
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


# ── sync helpers (run inside thread) ──────────────────────────────────────────

def _get_or_create_user(user_id: int, username: str, first_name: str) -> None:
    with _db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id, username, first_name) VALUES (?, ?, ?)",
            (user_id, username, first_name),
        )


def _has_paid(user_id: int) -> bool:
    with _db() as conn:
        cur = conn.execute("SELECT paid_at FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        return bool(row and row[0])


def _mark_user_paid(user_id: int, tribute_id: str) -> None:
    with _db() as conn:
        conn.execute(
            "UPDATE users SET paid_at = CURRENT_TIMESTAMP, stage = 'paid', drip_step = 99 WHERE id = ?",
            (user_id,),
        )
        conn.execute(
            "INSERT INTO payments (user_id, tribute_id, amount, status) VALUES (?, ?, 300, 'succeeded')",
            (user_id, tribute_id),
        )


def _update_stage(user_id: int, stage: str) -> None:
    with _db() as conn:
        conn.execute("UPDATE users SET stage = ? WHERE id = ?", (stage, user_id))


def _get_unreminded_users(hours: int, reminded_field: str):
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    with _db() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            f"SELECT id FROM users WHERE paid_at IS NULL AND {reminded_field} = 0 AND joined_at <= ?",
            (cutoff.isoformat(),),
        )
        return [dict(r) for r in cur.fetchall()]


def _mark_reminded(user_id: int, field: str) -> None:
    with _db() as conn:
        conn.execute(f"UPDATE users SET {field} = 1 WHERE id = ?", (user_id,))


def _get_stats():
    with _db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        paid = conn.execute("SELECT COUNT(*) FROM users WHERE paid_at IS NOT NULL").fetchone()[0]
        return total, paid


def _save_phone(user_id: int, phone: str) -> None:
    phone = phone.replace(" ", "").replace("-", "")
    if not phone.startswith("+"):
        phone = "+" + phone
    with _db() as conn:
        conn.execute("UPDATE users SET phone = ? WHERE id = ?", (phone, user_id))


def _get_user_id_by_phone(phone: str):
    phone = phone.replace(" ", "").replace("-", "")
    if not phone.startswith("+"):
        phone = "+" + phone
    with _db() as conn:
        cur = conn.execute("SELECT id FROM users WHERE phone = ?", (phone,))
        row = cur.fetchone()
        return row[0] if row else None


def _save_pending_payment(phone: str, email: str, order_id: str) -> None:
    with _db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO pending_payments (phone, email, order_id) VALUES (?, ?, ?)",
            (phone, email, order_id),
        )


def _pop_pending_payment_by_phone(phone: str):
    phone = phone.replace(" ", "").replace("-", "")
    if not phone.startswith("+"):
        phone = "+" + phone
    with _db() as conn:
        cur = conn.execute(
            "SELECT id, order_id FROM pending_payments WHERE phone = ? ORDER BY created_at DESC LIMIT 1",
            (phone,),
        )
        row = cur.fetchone()
        if not row:
            return None
        conn.execute("DELETE FROM pending_payments WHERE id = ?", (row[0],))
        return row[1]


def _get_all_user_ids():
    with _db() as conn:
        return [r[0] for r in conn.execute("SELECT id FROM users").fetchall()]


def _get_paid_users():
    with _db() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT id, username, first_name, paid_at FROM users WHERE paid_at IS NOT NULL")
        return [dict(r) for r in cur.fetchall()]


def _get_unpaid_users():
    with _db() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT id, username, first_name, stage, joined_at FROM users WHERE paid_at IS NULL ORDER BY joined_at DESC"
        )
        return [dict(r) for r in cur.fetchall()]


def _get_all_users():
    with _db() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT id, username, first_name, phone, stage, paid_at, joined_at FROM users ORDER BY joined_at DESC"
        )
        return [dict(r) for r in cur.fetchall()]


def _get_funnel_stats():
    with _db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        paid = conn.execute("SELECT COUNT(*) FROM users WHERE paid_at IS NOT NULL").fetchone()[0]
        new_today = conn.execute(
            "SELECT COUNT(*) FROM users WHERE date(joined_at) = date('now')"
        ).fetchone()[0]
        paid_today = conn.execute(
            "SELECT COUNT(*) FROM users WHERE date(paid_at) = date('now')"
        ).fetchone()[0]
        conn.row_factory = sqlite3.Row
        stages = conn.execute(
            "SELECT stage, COUNT(*) as cnt FROM users WHERE paid_at IS NULL GROUP BY stage ORDER BY cnt DESC"
        ).fetchall()
        return {
            "total": total,
            "paid": paid,
            "new_today": new_today,
            "paid_today": paid_today,
            "stages": [dict(r) for r in stages],
        }


def _reset_drip(user_id: int) -> None:
    with _db() as conn:
        conn.execute(
            "UPDATE users SET drip_started_at = CURRENT_TIMESTAMP, drip_step = 0 WHERE id = ?",
            (user_id,),
        )


def _get_drip_pending(step: int, min_hours: float):
    with _db() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """SELECT id FROM users
               WHERE paid_at IS NULL
                 AND id > 0
                 AND drip_step = ?
                 AND drip_started_at IS NOT NULL
                 AND drip_started_at <= datetime('now', ? || ' hours')""",
            (step, f"-{min_hours}"),
        )
        return [dict(r) for r in cur.fetchall()]


def _advance_drip(user_id: int, next_step: int) -> None:
    with _db() as conn:
        conn.execute("UPDATE users SET drip_step = ? WHERE id = ?", (next_step, user_id))


def _stop_drip(user_id: int) -> None:
    with _db() as conn:
        conn.execute("UPDATE users SET drip_step = 99 WHERE id = ?", (user_id,))


def _log_message(user_id: int, username: str, first_name: str, text: str) -> None:
    with _db() as conn:
        conn.execute(
            "INSERT INTO message_log (user_id, username, first_name, text) VALUES (?, ?, ?, ?)",
            (user_id, username, first_name, text),
        )


def _get_reply_stats(hours: int = 48):
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with _db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT user_id, username, first_name, text, received_at FROM message_log "
            "WHERE received_at >= ? ORDER BY received_at ASC",
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def _get_pending_payments():
    with _db() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM pending_payments ORDER BY created_at DESC")
        return [dict(r) for r in cur.fetchall()]


def _delete_user(user_id: int) -> None:
    with _db() as conn:
        conn.execute("DELETE FROM payments WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


# ── async public API ───────────────────────────────────────────────────────────

async def get_or_create_user(user_id, username, first_name):
    await asyncio.to_thread(_get_or_create_user, user_id, username, first_name)

async def has_paid(user_id):
    return await asyncio.to_thread(_has_paid, user_id)

async def mark_user_paid(user_id, tribute_id=""):
    await asyncio.to_thread(_mark_user_paid, user_id, tribute_id)

async def update_stage(user_id, stage):
    await asyncio.to_thread(_update_stage, user_id, stage)

async def get_unreminded_users(hours, reminded_field):
    return await asyncio.to_thread(_get_unreminded_users, hours, reminded_field)

async def mark_reminded(user_id, field):
    await asyncio.to_thread(_mark_reminded, user_id, field)

async def get_stats():
    return await asyncio.to_thread(_get_stats)

async def save_phone(user_id, phone):
    await asyncio.to_thread(_save_phone, user_id, phone)

async def get_user_id_by_phone(phone):
    return await asyncio.to_thread(_get_user_id_by_phone, phone)

async def save_pending_payment(phone, email, order_id):
    await asyncio.to_thread(_save_pending_payment, phone, email, order_id)

async def pop_pending_payment_by_phone(phone):
    return await asyncio.to_thread(_pop_pending_payment_by_phone, phone)

async def get_all_user_ids():
    return await asyncio.to_thread(_get_all_user_ids)

async def get_paid_users():
    return await asyncio.to_thread(_get_paid_users)

async def get_unpaid_users():
    return await asyncio.to_thread(_get_unpaid_users)

async def get_all_users():
    return await asyncio.to_thread(_get_all_users)

async def get_funnel_stats():
    return await asyncio.to_thread(_get_funnel_stats)

async def reset_drip(user_id: int):
    await asyncio.to_thread(_reset_drip, user_id)

async def get_drip_pending(step: int, min_hours: float):
    return await asyncio.to_thread(_get_drip_pending, step, min_hours)

async def advance_drip(user_id: int, next_step: int):
    await asyncio.to_thread(_advance_drip, user_id, next_step)

async def stop_drip(user_id: int):
    await asyncio.to_thread(_stop_drip, user_id)

async def log_message(user_id: int, username: str, first_name: str, text: str):
    await asyncio.to_thread(_log_message, user_id, username, first_name, text)

async def get_reply_stats(hours: int = 48):
    return await asyncio.to_thread(_get_reply_stats, hours)

async def get_pending_payments():
    return await asyncio.to_thread(_get_pending_payments)

async def delete_user(user_id: int):
    await asyncio.to_thread(_delete_user, user_id)
