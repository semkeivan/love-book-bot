"""Автономный ежедневный отчёт.

Запускается отдельной задачей GitHub Actions раз в день (по cron), НЕ зависит от
процесса бота. Читает статистику из Turso и шлёт её админу в Telegram.
Env: TURSO_URL, TURSO_TOKEN, BOT_TOKEN, ADMIN_IDS.
"""
import os
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

TURSO_URL = os.environ["TURSO_URL"]
TURSO_TOKEN = os.environ["TURSO_TOKEN"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = os.environ["ADMIN_IDS"].split(",")[0].strip()


def _http_url():
    u = TURSO_URL
    return "https://" + u[9:] if u.startswith("libsql://") else u


def sql(query):
    body = json.dumps({"requests": [
        {"type": "execute", "stmt": {"sql": query}},
        {"type": "close"},
    ]}).encode()
    req = urllib.request.Request(
        f"{_http_url()}/v2/pipeline", data=body,
        headers={"Authorization": f"Bearer {TURSO_TOKEN}", "Content-Type": "application/json"},
    )
    res = json.loads(urllib.request.urlopen(req, timeout=20).read())["results"][0]
    if res["type"] != "ok":
        raise RuntimeError(res.get("error"))
    r = res["response"]["result"]
    cols = [c["name"] for c in r["cols"]]
    return [dict(zip(cols, [c.get("value") for c in row])) for row in r["rows"]]


def one(query, default=0):
    rows = sql(query)
    if rows:
        v = list(rows[0].values())[0]
        try:
            return int(v)
        except (TypeError, ValueError):
            return v
    return default


def send(text):
    payload = json.dumps({"chat_id": int(ADMIN_ID), "text": text, "parse_mode": "HTML",
                          "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                                 data=payload, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=20)


def main():
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    y = yesterday.isoformat()
    t = today.isoformat()

    total = one("SELECT COUNT(*) FROM users")
    paid = one("SELECT COUNT(*) FROM users WHERE paid_at IS NOT NULL")
    unpaid = total - paid
    conv = round(paid / total * 100, 1) if total else 0

    new_y = one(f"SELECT COUNT(*) FROM users WHERE date(joined_at)='{y}'")
    paid_y = one(f"SELECT COUNT(*) FROM users WHERE date(paid_at)='{y}'")
    new_t = one(f"SELECT COUNT(*) FROM users WHERE date(joined_at)='{t}'")
    paid_t = one(f"SELECT COUNT(*) FROM users WHERE date(paid_at)='{t}'")

    stages = sql("SELECT stage, COUNT(*) c FROM users WHERE paid_at IS NULL GROUP BY stage ORDER BY c DESC")
    labels = {
        "new": "нажали /start, не купили",
        "asked_q1": "вопрос 1", "asked_q2": "вопрос 2", "asked_q3": "вопрос 3",
        "asked_q4": "вопрос 4", "asked_q5": "вопрос 5",
    }
    stage_lines = "\n".join(f"  • {labels.get(s['stage'], s['stage'])}: {s['c']}" for s in stages) or "  —"

    # кто именно оплатил вчера
    paid_y_list = sql(f"SELECT first_name, username FROM users WHERE date(paid_at)='{y}'")
    who = "\n".join(
        f"  💰 {(u.get('first_name') or '').strip()} @{u.get('username') or '—'}" for u in paid_y_list
    )

    text = (
        f"📊 <b>Ежедневный отчёт</b> — {yesterday.strftime('%d.%m.%Y')}\n\n"
        f"<b>За вчера:</b>\n"
        f"  👋 Зашло новых: <b>{new_y}</b>\n"
        f"  💰 Оплатили: <b>{paid_y}</b>\n"
        + (who + "\n" if who else "")
        + f"\n<b>Сегодня пока:</b>\n"
        f"  👋 Зашло: {new_t}   💰 Оплат: {paid_t}\n\n"
        f"<b>Всего в базе:</b>\n"
        f"  👥 Лидов: <b>{total}</b>\n"
        f"  💰 Оплатили: <b>{paid}</b>  ({conv}%)\n"
        f"  🔄 Не оплатили: <b>{unpaid}</b>\n\n"
        f"<b>Неоплатившие по стадиям:</b>\n{stage_lines}\n\n"
        f"🔗 Панель: https://relearn-whiff-pusher.ngrok-free.dev/admin/dashboard?token={ADMIN_ID}"
    )
    send(text)
    print("report sent")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Хотя бы уведомим, что отчёт сломался
        try:
            send(f"⚠️ Ежедневный отчёт не собрался: {e}")
        except Exception:
            pass
        raise
