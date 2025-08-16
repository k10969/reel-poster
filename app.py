# app.py — Flask Web UI (Py3.9 safe) / 投稿・ログ・ランダムテキスト・アカウント管理
from __future__ import annotations

import os
import json
import traceback
from pathlib import Path
from typing import Optional, Dict, List, Any

from flask import (
    Flask, render_template, request, redirect, url_for,
    jsonify, send_from_directory, Response
)
from werkzeug.utils import secure_filename

# 依存（requirements.txt に moviepy, Pillow, requests, cloudinary 等）
from moviepy.editor import VideoFileClip
from PIL import Image

# ========== optional: settings_store ==========
def _try_import_settings_store():
    try:
        import settings_store as s  # type: ignore
        return s
    except Exception:
        return None

SSTORE = _try_import_settings_store()

# ========== 自前中核 ==========
from poster_core_reel import PosterCoreReel

# ========== パス ==========
BASE_DIR: Path = Path(__file__).resolve().parent
STATIC_DIR: Path = BASE_DIR / "static"
TEMPLATES_DIR: Path = BASE_DIR / "templates"
LOG_DIR: Path = BASE_DIR / "logs"

OVERLAY_DIR: Path = STATIC_DIR / "overlay_input"
THUMBS_DIR: Path = STATIC_DIR / "thumbs"
BACKGROUND_DIR: Path = STATIC_DIR / "backgrounds"
OUTPUT_DIR: Path = STATIC_DIR / "output"

for d in (STATIC_DIR, TEMPLATES_DIR, LOG_DIR, OVERLAY_DIR, THUMBS_DIR, BACKGROUND_DIR, OUTPUT_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ========== Flask ==========
app = Flask(__name__, static_folder=str(STATIC_DIR), template_folder=str(TEMPLATES_DIR))

# ========== ストレージ ==========
ACCOUNTS_JSON = BASE_DIR / "accounts.json"
OVERRIDES_JSON = BASE_DIR / "material_overrides.json"
ORDER_JSON = BASE_DIR / "materials_order.json"
RANDOM_TXT = BASE_DIR / "random_texts.txt"

# ---- accounts load/save ----
def load_accounts_any() -> List[Dict[str, Any]]:
    if SSTORE:
        try:
            data = SSTORE.load_accounts()
            if isinstance(data, dict):
                accs = data.get("accounts", [])
                if isinstance(accs, list) and accs:
                    return accs
        except Exception:
            pass
    if ACCOUNTS_JSON.exists():
        try:
            d = json.loads(ACCOUNTS_JSON.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                accs = d.get("accounts", [])
                if isinstance(accs, list):
                    return accs
        except Exception:
            pass
    return []

def save_accounts_any(accounts: List[Dict[str, Any]]) -> None:
    payload = {"accounts": accounts}
    saved = False
    if SSTORE:
        try:
            SSTORE.save_accounts(payload)  # type: ignore
            saved = True
        except Exception:
            saved = False
    if not saved:
        ACCOUNTS_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

# ---- overrides ----
def load_overrides() -> Dict[str, str]:
    if SSTORE:
        try:
            return SSTORE.load_overrides()
        except Exception:
            pass
    if OVERRIDES_JSON.exists():
        try:
            return json.loads(OVERRIDES_JSON.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_overrides(data: Dict[str, str]) -> None:
    if SSTORE:
        try:
            SSTORE.save_overrides(data)
            return
        except Exception:
            pass
    OVERRIDES_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# ---- order ----
def load_materials_order() -> List[str]:
    if SSTORE:
        try:
            return SSTORE.load_materials_order()
        except Exception:
            pass
    if ORDER_JSON.exists():
        try:
            return json.loads(ORDER_JSON.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def save_materials_order(order: List[str]) -> None:
    if SSTORE:
        try:
            SSTORE.save_materials_order(order)
            return
        except Exception:
            pass
    ORDER_JSON.write_text(json.dumps(order, ensure_ascii=False, indent=2), encoding="utf-8")

# ---- random texts ----
def load_random_texts() -> str:
    if SSTORE:
        try:
            return SSTORE.load_random_texts()
        except Exception:
            pass
    if RANDOM_TXT.exists():
        try:
            return RANDOM_TXT.read_text(encoding="utf-8")
        except Exception:
            return ""
    return ""

def save_random_texts(body: str) -> None:
    if SSTORE:
        try:
            SSTORE.save_random_texts(body)
            return
        except Exception:
            pass
    RANDOM_TXT.write_text(body, encoding="utf-8")

# ========== ユーティリティ ==========
ALLOWED_EXTS = {
    "jpg", "jpeg", "png", "bmp", "gif", "webp",
    "mp4", "mov", "m4v", "avi", "mkv", "webm"
}

def _is_allowed(filename: str) -> bool:
    ext = filename.rsplit(".", 1)[-1].lower()
    return ext in ALLOWED_EXTS

def _thumb_path_for(filename: str) -> Path:
    return THUMBS_DIR / f"{filename}.jpg"

def _ensure_thumb(material_path: Path) -> str:
    thumb_path = _thumb_path_for(material_path.name)
    if thumb_path.exists():
        return f"/static/thumbs/{thumb_path.name}"
    ext = material_path.suffix.lower().lstrip(".")
    try:
        if ext in {"mp4", "mov", "m4v", "avi", "mkv", "webm"}:
            clip = VideoFileClip(str(material_path))
            t = 1.0
            try:
                if clip.duration and clip.duration < 1.0:
                    t = 0.0
            except Exception:
                t = 0.0
            clip.save_frame(str(thumb_path), t=t)
            clip.close()
        else:
            with Image.open(str(material_path)) as im:
                im = im.convert("RGB")
                im.thumbnail((480, 480))
                im.save(str(thumb_path), "JPEG", quality=85)
    except Exception:
        try:
            with Image.new("RGB", (1, 1), (255, 255, 255)) as im:
                im.save(str(thumb_path), "JPEG", quality=80)
        except Exception:
            pass
    return f"/static/thumbs/{thumb_path.name}"

def list_materials() -> List[Dict[str, Any]]:
    overrides = load_overrides()
    order = load_materials_order()

    files: List[str] = []
    for p in sorted(OVERLAY_DIR.iterdir()):
        if p.is_file() and _is_allowed(p.name):
            files.append(p.name)

    if order:
        order_index = {n: i for i, n in enumerate(order)}
        files.sort(key=lambda n: order_index.get(n, 10_000_000))

    items: List[Dict[str, Any]] = []
    for name in files:
        thumb_url = _ensure_thumb(OVERLAY_DIR / name)
        items.append({
            "filename": name,
            "thumb_url": thumb_url,
            "comment": overrides.get(name, "")
        })
    return items

def pick_background_for_account(account_no: int) -> Optional[Path]:
    candidates = [
        BACKGROUND_DIR / f"{account_no}.mp4",
        BACKGROUND_DIR / f"background{account_no}.mp4",
        BACKGROUND_DIR / f"{account_no}.mov",
        BACKGROUND_DIR / f"background{account_no}.mov",
    ]
    for c in candidates:
        if c.exists():
            return c
    for p in BACKGROUND_DIR.iterdir():
        if p.suffix.lower() in {".mp4", ".mov", ".m4v"}:
            return p
    return None

# ========== ルート ==========
@app.get("/health")
def health():
    return jsonify(ok=True)

@app.get("/")
def index():
    accounts = load_accounts_any()
    materials = list_materials()
    random_texts_body = load_random_texts()
    return render_template(
        "index.html",
        accounts=accounts,
        materials=materials,
        random_texts=random_texts_body
    )

# 素材アップロード
@app.post("/upload")
def upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return redirect(url_for("index"))
    fname = secure_filename(f.filename)
    if not _is_allowed(fname):
        return redirect(url_for("index"))
    save_path = OVERLAY_DIR / fname
    f.save(str(save_path))
    _ensure_thumb(save_path)
    return redirect(url_for("index"))

# コメント保存（素材1:1）
@app.post("/api/override")
def api_override():
    try:
        payload = request.get_json(force=True)
        filename = str(payload.get("filename", "")).strip()
        text = str(payload.get("text", ""))
        if not filename:
            return jsonify(ok=False, error="filename is required"), 400
        overrides = load_overrides()
        overrides[filename] = text
        save_overrides(overrides)
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500

# ランダムテキスト
@app.get("/api/random_texts")
def api_random_texts_get():
    return jsonify(ok=True, body=load_random_texts())

@app.post("/api/random_texts")
def api_random_texts_post():
    try:
        body = request.get_data(as_text=True) or ""
        save_random_texts(body)
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500

# 並び順 保存
@app.post("/api/materials_order")
def api_materials_order():
    try:
        payload = request.get_json(force=True)
        order = payload.get("order", [])
        if not isinstance(order, list):
            order = []
        existing = {p.name for p in OVERLAY_DIR.iterdir() if p.is_file()}
        order = [n for n in order if n in existing]
        save_materials_order(order)
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500

# 投稿（選択のみ）
@app.post("/publish_selected")
def publish_selected():
    try:
        account_no = int(request.form.get("account_no", "1"))
        filename = (request.form.get("filename") or "").strip()
        comment = request.form.get("comment", "")
        share_to_feed = request.form.get("share_to_feed") == "on"

        if not filename:
            return jsonify(ok=False, error="filename required"), 400

        overlay_path = OVERLAY_DIR / filename
        if not overlay_path.exists():
            return jsonify(ok=False, error="overlay not found"), 404

        bg_path = pick_background_for_account(account_no)
        if not bg_path:
            return jsonify(ok=False, error="background not found"), 404

        core = PosterCoreReel()
        media_id = core.post_reel(
            account_no=account_no,
            overlay_path=overlay_path,
            background_path=bg_path,
            custom_overlay_text=comment if comment.strip() else None,
            share_to_feed=share_to_feed,
        )
        return jsonify(ok=True, media_id=str(media_id))
    except Exception as e:
        # ここで500返すとフロント側がHTML受ける可能性→JS側でtext fallback対応済み
        return jsonify(ok=False, error=str(e), tb=traceback.format_exc()), 500

# 投稿（並び順で全部） + 全アカウント対応
@app.post("/publish_all_ordered")
def publish_all_ordered():
    try:
        accs = load_accounts_any()
        account_no = int(request.form.get("account_no", "1"))
        all_accounts_flag = request.form.get("all_accounts") == "on"
        share_to_feed = request.form.get("share_to_feed") == "on"

        target_nos: List[int]
        if all_accounts_flag:
            target_nos = []
            for a in accs:
                try:
                    n = int(str(a.get("no", "1")))
                    target_nos.append(n)
                except Exception:
                    continue
            target_nos = sorted(set(target_nos)) or [account_no]
        else:
            target_nos = [account_no]

        order = load_materials_order()
        if not order:
            order = []
            for p in sorted(OVERLAY_DIR.iterdir()):
                if p.is_file() and _is_allowed(p.name):
                    order.append(p.name)

        overrides = load_overrides()
        core = PosterCoreReel()

        results: List[Dict[str, Any]] = []
        for no in target_nos:
            bg = pick_background_for_account(no)
            if not bg:
                results.append({"account_no": no, "ok": False, "error": "background not found"})
                continue
            for fname in order:
                overlay = OVERLAY_DIR / fname
                if not overlay.exists():
                    results.append({"account_no": no, "filename": fname, "ok": False, "error": "overlay not found"})
                    continue
                comment = (overrides.get(fname, "") or "").strip() or None
                try:
                    media_id = core.post_reel(
                        account_no=no,
                        overlay_path=overlay,
                        background_path=bg,
                        custom_overlay_text=comment,
                        share_to_feed=share_to_feed,
                    )
                    results.append({"account_no": no, "filename": fname, "ok": True, "media_id": str(media_id)})
                except Exception as e:
                    results.append({"account_no": no, "filename": fname, "ok": False, "error": str(e)})
        return jsonify(ok=True, results=results)
    except Exception as e:
        return jsonify(ok=False, error=str(e), tb=traceback.format_exc()), 500

# ---- 投稿ログAPI ----
def _tail(path: Path, max_bytes: int = 50000) -> str:
    if not path.exists():
        return ""
    try:
        size = path.stat().st_size
        if size <= max_bytes:
            return path.read_text(encoding="utf-8", errors="ignore")
        with path.open("rb") as f:
            f.seek(max(0, size - max_bytes))
            data = f.read().decode("utf-8", errors="ignore")
            return data
    except Exception:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""

@app.get("/api/logs")
def api_logs():
    name = (request.args.get("name") or "all").lower()
    ig_log = LOG_DIR / "ig_publisher.log"
    core_log = LOG_DIR / "core.log"
    body = ""
    if name in ("ig", "instagram"):
        body = _tail(ig_log)
    elif name in ("core", "movie", "compose"):
        body = _tail(core_log)
    else:
        body = "=== ig_publisher.log ===\n" + _tail(ig_log) + "\n\n=== core.log ===\n" + _tail(core_log)
    return Response(body, mimetype="text/plain; charset=utf-8")

# ---- アカウント管理API ----
@app.get("/api/accounts")
def api_accounts_get():
    return jsonify(ok=True, accounts=load_accounts_any())

@app.post("/api/accounts")
def api_accounts_post():
    """
    JSON:
      action: "add" | "update" | "delete"
      account: {no, label, ig_user_id, page_id, access_token}
      no: 対象番号（delete/update用）
    """
    try:
        payload = request.get_json(force=True) or {}
        action = str(payload.get("action", "")).lower()
        accounts = load_accounts_any()

        if action == "add":
            acc = payload.get("account", {}) or {}
            # 既存no重複なら上書き、なければappend
            no = str(acc.get("no", "")).strip()
            if not no:
                return jsonify(ok=False, error="no required"), 400
            # normalize
            acc_norm = {
                "no": no,
                "label": acc.get("label", "") or no,
                "ig_user_id": acc.get("ig_user_id", "") or "",
                "page_id": acc.get("page_id", "") or "",
                "access_token": acc.get("access_token", "") or "",
            }
            updated = False
            for i, a in enumerate(accounts):
                if str(a.get("no")) == no:
                    accounts[i] = acc_norm
                    updated = True
                    break
            if not updated:
                accounts.append(acc_norm)
            save_accounts_any(accounts)
            return jsonify(ok=True, accounts=accounts)

        elif action == "update":
            acc = payload.get("account", {}) or {}
            no = str(acc.get("no", "")).strip()
            if not no:
                return jsonify(ok=False, error="no required"), 400
            for i, a in enumerate(accounts):
                if str(a.get("no")) == no:
                    accounts[i] = {
                        "no": no,
                        "label": acc.get("label", "") or no,
                        "ig_user_id": acc.get("ig_user_id", "") or "",
                        "page_id": acc.get("page_id", "") or "",
                        "access_token": acc.get("access_token", "") or "",
                    }
                    save_accounts_any(accounts)
                    return jsonify(ok=True, accounts=accounts)
            return jsonify(ok=False, error="account not found"), 404

        elif action == "delete":
            no = str(payload.get("no", "")).strip()
            if not no:
                return jsonify(ok=False, error="no required"), 400
            accounts = [a for a in accounts if str(a.get("no")) != no]
            save_accounts_any(accounts)
            return jsonify(ok=True, accounts=accounts)

        else:
            return jsonify(ok=False, error="unknown action"), 400

    except Exception as e:
        return jsonify(ok=False, error=str(e), tb=traceback.format_exc()), 500

# 静的
@app.get("/static/<path:filename>")
def static_files(filename: str):
    return send_from_directory(str(STATIC_DIR), filename, as_attachment=False)

# ローカル確認
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=True)
