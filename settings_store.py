# settings_store.py — Python 3.9 互換（Optional/Dict/List を使用）
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple

BASE_DIR: Path = Path(__file__).resolve().parent

# データファイル
ACCOUNTS_PATH: Path = BASE_DIR / "accounts.json"
ORDER_PATH: Path = BASE_DIR / "materials_order.json"
OVERRIDES_PATH: Path = BASE_DIR / "material_overrides.json"
RANDOM_TEXTS_PATH: Path = BASE_DIR / "random_texts.txt"

# ========== 共通ユーティリティ ==========
def _safe_read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            return default
        data = json.loads(text)
        return data
    except Exception:
        return default

def _safe_write_json(path: Path, obj: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        # 失敗してもアプリは落とさない
        pass

# ========== アカウント ==========
# スキーマ: {"accounts": [{"no":"1","label":"...","ig_user_id":"...","page_id":"...","access_token":"..."}, ...]}
def load_accounts() -> Dict[str, Any]:
    data = _safe_read_json(ACCOUNTS_PATH, {"accounts": []})
    # 最低限の整形
    if not isinstance(data, dict):
        data = {"accounts": []}
    accounts = data.get("accounts", [])
    if not isinstance(accounts, list):
        accounts = []
    # 文字列化＆キーを補完
    normed: List[Dict[str, str]] = []
    for a in accounts:
        if not isinstance(a, dict):
            continue
        normed.append({
            "no": str(a.get("no", "")).strip(),
            "label": str(a.get("label", "")),
            "ig_user_id": str(a.get("ig_user_id", "")),
            "page_id": str(a.get("page_id", "")),
            "access_token": str(a.get("access_token", "")),
        })
    return {"accounts": normed}

def save_accounts(data: Dict[str, Any]) -> None:
    # フォーマットを強制
    if not isinstance(data, dict):
        data = {"accounts": []}
    accounts = data.get("accounts", [])
    if not isinstance(accounts, list):
        accounts = []
    normed: List[Dict[str, str]] = []
    for a in accounts:
        if not isinstance(a, dict):
            continue
        normed.append({
            "no": str(a.get("no", "")).strip(),
            "label": str(a.get("label", "")),
            "ig_user_id": str(a.get("ig_user_id", "")),
            "page_id": str(a.get("page_id", "")),
            "access_token": str(a.get("access_token", "")),
        })
    _safe_write_json(ACCOUNTS_PATH, {"accounts": normed})

# ========== 並び順（任意） ==========
def load_materials_order() -> List[str]:
    arr = _safe_read_json(ORDER_PATH, [])
    return arr if isinstance(arr, list) else []

def save_materials_order(order: List[str]) -> None:
    if not isinstance(order, list):
        order = []
    _safe_write_json(ORDER_PATH, order)

# ========== 素材ごとのコメント（任意） ==========
def load_overrides() -> Dict[str, str]:
    d = _safe_read_json(OVERRIDES_PATH, {})
    if isinstance(d, dict):
        # 値は文字列化
        return {str(k): str(v) for k, v in d.items()}
    return {}

def save_overrides(overrides: Dict[str, str]) -> None:
    if not isinstance(overrides, dict):
        overrides = {}
    # 文字列に寄せる
    safe = {str(k): str(v) for k, v in overrides.items()}
    _safe_write_json(OVERRIDES_PATH, safe)

# ========== ランダムテキスト（任意） ==========
def load_random_texts() -> str:
    if RANDOM_TEXTS_PATH.exists():
        try:
            return RANDOM_TEXTS_PATH.read_text(encoding="utf-8")
        except Exception:
            return ""
    return ""

def save_random_texts(body: str) -> None:
    try:
        RANDOM_TEXTS_PATH.write_text(body if isinstance(body, str) else "", encoding="utf-8")
    except Exception:
        pass

# ========== （任意）クラウドバックアップ/リストアのダミー ==========
# app.py から import されるので存在だけ用意。必要なら実装を拡張してください。
def cloud_backup() -> Dict[str, Any]:
    # ここで Cloudinary や S3 にバックアップしたい場合は実装
    return {
        "ok": True,
        "saved": {
            "accounts": ACCOUNTS_PATH.exists(),
            "order": ORDER_PATH.exists(),
            "overrides": OVERRIDES_PATH.exists(),
            "random_texts": RANDOM_TEXTS_PATH.exists(),
        }
    }

def cloud_restore() -> None:
    # ここでクラウドからローカルに復元したい場合は実装
    # 未実装でもアプリは動く（no-op）
    return None
