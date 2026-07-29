import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
TURSO_URL = os.getenv("TURSO_URL", "")
TURSO_TOKEN = os.getenv("TURSO_TOKEN", "")
TRIBUTE_PAYMENT_LINK = os.getenv("TRIBUTE_PAYMENT_LINK", "")
TRIBUTE_WEBHOOK_SECRET = os.getenv("TRIBUTE_WEBHOOK_SECRET", "")
COMMUNITY_CHAT_LINK = os.getenv("COMMUNITY_CHAT_LINK", "https://t.me/semke_youtube")
PAYMENT_SECRET = os.getenv("PAYMENT_SECRET", "change_me")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
PDF_PATH = Path(__file__).parent / "assets" / "love_book.pdf"
COVER_PATH = Path(__file__).parent / "assets" / "book_cover.jpg"
# На fly.io — /data (persistent volume), локально — рядом с проектом
_data_dir = Path(os.getenv("DATA_DIR", str(Path(__file__).parent)))
DB_PATH = _data_dir / "buyers.db"
WEBHOOK_PORT = int(os.getenv("PORT", os.getenv("WEBHOOK_PORT", "8080")))
FLY_APP_NAME = os.getenv("FLY_APP_NAME", "")
RAILWAY_DOMAIN = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
PUBLIC_URL = (
    f"https://{RAILWAY_DOMAIN}" if RAILWAY_DOMAIN
    else f"https://{FLY_APP_NAME}.fly.dev" if FLY_APP_NAME
    else os.getenv("PUBLIC_URL", "")
)
