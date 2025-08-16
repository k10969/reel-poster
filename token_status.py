# token_status.py
import os, time, requests
from pathlib import Path
from dotenv import load_dotenv

BASE = Path(__file__).parent.resolve()
load_dotenv(BASE / ".env", override=False)

APP_ID = os.getenv("FB_APP_ID")
APP_SECRET = os.getenv("FB_APP_SECRET")

class TokenError(RuntimeError): ...
FB_API = "https://graph.facebook.com/v22.0"

def _app_access_token() -> str:
    if not (APP_ID and APP_SECRET):
        raise TokenError("FB_APP_ID / FB_APP_SECRET が .env にありません")
    r = requests.get(f"{FB_API}/oauth/access_token", params={
        "client_id": APP_ID, "client_secret": APP_SECRET, "grant_type": "client_credentials"
    }, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]

def debug_token(token: str) -> dict:
    app_tok = _app_access_token()
    r = requests.get("https://graph.facebook.com/debug_token", params={
        "input_token": token, "access_token": app_tok
    }, timeout=30)
    r.raise_for_status()
    return r.json().get("data", {})

def owner_token_status(owner_token: str) -> dict:
    if not owner_token:
        raise TokenError("OWNER_USER_TOKEN が空です")
    data = debug_token(owner_token)
    exp = int(data.get("expires_at") or 0)
    now = int(time.time())
    remaining_days = (exp - now) // 86400 if exp else None
    return {
        "type": data.get("type"),
        "expires_at": exp or None,
        "remaining_days": remaining_days,
        "is_valid": bool(data.get("is_valid", False)),
        "scopes": data.get("scopes", []),
        "user_id": data.get("user_id"),
        "app_id": data.get("app_id"),
    }
