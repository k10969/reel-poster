# settings_store.py
# 設定/アカウントを data/ に保存し、（任意で）Cloudinary raw へバックアップ/復元。
# さらにレガシー位置/形式の accounts.json を自動取り込み（マイグレーション）します。

from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

ACCOUNTS_PATH = DATA_DIR / "accounts.json"
SETTINGS_PATH = DATA_DIR / "settings.json"

# --- レガシー探索先（昔の配置を想定） ---
LEGACY_PATHS = [
    BASE_DIR / "accounts.json",                 # ルート直下
    BASE_DIR / "static" / "accounts.json",      # static配下
]

# --- Cloudinary は任意（無ければバックアップ機能は無効） ---
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


# -----------------------------
# 基本ユーティリティ
# -----------------------------
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
# レガシー → 正規形 変換
# -----------------------------
def _normalize_accounts(obj: Any) -> Dict[str, Any]:
    """
    いろんな形を {'accounts':[...]} に正規化する。
    - dict で 'accounts' キーがリスト → そのまま
    - dict で list/ items/ data のいずれかがリスト → accounts に詰め替え
    - dict で単一レコードっぽい → 1件のリストに
    - list → accounts に入れる
    それ以外は空配列。
    """
    if isinstance(obj, dict):
        if "accounts" in obj and isinstance(obj["accounts"], list):
            return {"accounts": obj["accounts"]}
        for k in ("list", "items", "data"):
            if k in obj and isinstance(obj[k], list):
                return {"accounts": obj[k]}
        # 単一レコード（ざっくり判定）
        if obj and all(not isinstance(v, (list, dict)) for v in obj.values()):
            return {"accounts": [obj]}
        return {"accounts": []}
    if isinstance(obj, list):
        return {"accounts": obj}
    return {"accounts": []}


def _maybe_migrate_legacy() -> bool:
    """
    data/accounts.json が無いとき、レガシー位置の accounts.json を探して
    正規化して移し替える。成功したら True。
    """
    if ACCOUNTS_PATH.exists():
        return False
    for p in LEGACY_PATHS:
        if p.exists():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                norm = _normalize_accounts(raw)
                _write_json(ACCOUNTS_PATH, norm)
                return True
            except Exception:
                continue
    return False


# -----------------------------
# 公開API：ローカル保存
# -----------------------------
def load_accounts() -> Dict[str, Any]:
    """{"accounts":[...]} を返す。無ければレガシーから自動移行を試す。"""
    if not ACCOUNTS_PATH.exists():
        _maybe_migrate_legacy()
    data = _read_json(ACCOUNTS_PATH, {"accounts": []})
    return _normalize_accounts(data)


def save_accounts(data: Dict[str, Any]) -> None:
    if not isinstance(data, dict):
        data = {"accounts": []}
    # 正規化してから保存（念のため）
    norm = _normalize_accounts(data)
    _write_json(ACCOUNTS_PATH, norm)


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
    """
    accounts.json / settings.json を Cloudinary raw として上書きアップロード。
    Cloudinary未設定なら何もしない（空dict返却）。
    """
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
    """
    Cloudinary から raw を取得してローカルに復元。無ければスキップ。
    Cloudinary未設定でも何もしない。
    """
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
