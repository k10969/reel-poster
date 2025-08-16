# creds_manager.py
import json, time
from pathlib import Path
from typing import Dict, Any, List, Optional

ACCOUNTS_FILE = Path("accounts.json")

def _load() -> Dict[str, Any]:
    if ACCOUNTS_FILE.exists():
        try:
            return json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"default_account_no": 1, "accounts": []}

def _save(data: Dict[str, Any]) -> None:
    ACCOUNTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def list_accounts() -> List[Dict[str, Any]]:
    return _load().get("accounts", [])

def get_account(no: int) -> Optional[Dict[str, Any]]:
    for a in list_accounts():
        if int(a.get("no", 0)) == int(no):
            return a
    return None

def upsert_account(no: int, label: str, ig_user_id: str, access_token: str) -> Dict[str, Any]:
    data = _load()
    accs = data.setdefault("accounts", [])
    found = None
    for a in accs:
        if int(a.get("no", 0)) == int(no):
            found = a
            break
    if found is None:
        found = {"no": int(no)}
        accs.append(found)
    found.update({
        "label": label,
        "ig_user_id": str(ig_user_id),
        "access_token": str(access_token),
        # メタ情報（更新系）
        "last_refresh_ts": float(found.get("last_refresh_ts", 0.0)),
        "expires_in": int(found.get("expires_in", 0)),
    })
    _save(data)
    return found

def update_account_token(no: int, new_token: str, expires_in: int = 0) -> None:
    data = _load()
    for a in data.get("accounts", []):
        if int(a.get("no", 0)) == int(no):
            a["access_token"] = new_token
            a["last_refresh_ts"] = time.time()
            a["expires_in"] = int(expires_in or 0)
            break
    _save(data)
