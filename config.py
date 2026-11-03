import os
import sys
from pathlib import Path

# Load local .env if present without external dependencies
env_path = Path(__file__).resolve().parent / ".env"
if env_path.is_file():
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip("'\"")
            os.environ.setdefault(k.strip(), v)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "").strip()
AI_ENABLED = os.getenv("AI_ENABLED", "true").lower() in ("true", "1", "yes")

try:
    SECONDS_PER_LAP = float(os.getenv("SECONDS_PER_LAP", "8"))
except ValueError:
    SECONDS_PER_LAP = 8.0

try:
    PORT = int(os.getenv("PORT", "8080"))
except ValueError:
    PORT = 8080

def validate_bot_config(webhook: bool = False) -> None:
    if not TELEGRAM_BOT_TOKEN:
        sys.exit("Error: TELEGRAM_BOT_TOKEN environment variable is missing.")
    if webhook:
        if not WEBHOOK_URL:
            sys.exit("Error: WEBHOOK_URL environment variable is missing for webhook mode.")
        if not WEBHOOK_SECRET:
            sys.exit("Error: WEBHOOK_SECRET environment variable is missing for webhook mode.")
    if AI_ENABLED:
        validate_gemini_config()

def validate_gemini_config() -> None:
    if not GEMINI_API_KEY:
        sys.exit("Error: GEMINI_API_KEY environment variable is missing.")
    if not GEMINI_MODEL:
        sys.exit("Error: GEMINI_MODEL environment variable is missing.")
