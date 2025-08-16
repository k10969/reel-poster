# settings_store.py
# 設定/アカウントの保存先を data/ 配下にまとめ、
# さらに Cloudinary(raw) にバックアップ/復元（Cloudinaryが使える場合のみ）。

from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

ACCOUNTS_PATH = DATA_DIR / "accounts.json"
SETTINGS_PATH = DATA_DIR / "settings.json"

# --- Cloudinary は任意（無ければバックアップ機能は無効でOK） ---
try:
    import cloudinary
    import cloudinary.uploader
    import cloudinary.api
    _CLOUD_AVAILABLE = True
except Exception:
    _CLOUD_AVAILABLE = False

CLOUD_BACKUP_FOLDER = "video_reel_settings"
ACCOUNTS_PID = "accounts.json"
SETTINGS_PID = "settings.json"


def _read_json(path: Path, default: Any) -> Any:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


# -----------------------------
# 公開API：ローカル保存
# -----------------------------
def load_accounts() -> Dict[str, Any]:
    """{"accounts":[...]} を返す。無ければ空で作る。"""
    data = _read_json(ACCOUNTS_PATH, {"accounts": []})
    if not isinstance(data, dict) or "accounts" not in data:
        data = {"accounts": []}
    return data


def save_accounts(data: Dict[str, Any]) -> None:
    if not isinstance(data, dict):
        data = {"accounts": []}
    _write_json(ACCOUNTS_PATH, data)


def load_settings() -> Dict[str, Any]:
    """settings.json の読み取り（無ければ空dict）"""
    data = _read_json(SETTINGS_PATH, {})
    if not isinstance(data, dict):
        data = {}
    return data


def save_settings(js: Dict[str, Any]) -> None:
    if not isinstance(js, dict):
        js = {}
    _write_json(SETTINGS_PATH, js)


# -----------------------------
# 任意機能：Cloudinary バックアップ/復元
# -----------------------------
def cloud_backup() -> Dict[str, Any]:
    """accounts.json / settings.json を Cloudinary raw として上書きアップロード。
       Cloudinary未設定なら何もしない（空dict）。"""
    if not _CLOUD_AVAILABLE:
        return {}

    out = {}
    for local_path, public_id in [(ACCOUNTS_PATH, ACCOUNTS_PID), (SETTINGS_PATH, SETTINGS_PID)]:
        if local_path.exists():
            res = cloudinary.uploader.upload(
                str(local_path),
                folder=CLOUD_BACKUP_FOLDER,
                resource_type="raw",
                public_id=public_id,
                overwrite=True,
            )
            out[public_id] = {"version": res.get("version")}
    return out


def cloud_restore() -> None:
    """Cloudinary から raw を取得してローカルに復元。無ければスキップ。
       Cloudinary未設定でも何もしない。"""
    if not _CLOUD_AVAILABLE:
        return

    import urllib.request
    for public_id, local in [(ACCOUNTS_PID, ACCOUNTS_PATH), (SETTINGS_PID, SETTINGS_PATH)]:
        try:
            meta = cloudinary.api.resource(
                f"{CLOUD_BACKUP_FOLDER}/{public_id}",
                resource_type="raw"
            )
            url = meta.get("secure_url")
            if url:
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                with urllib.request.urlopen(url, timeout=30) as resp:
                    content = resp.read()
                local.write_bytes(content)
        except Exception:
            # 無ければ/失敗時はスキップ
            pass
