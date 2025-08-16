import os
import json
from pathlib import Path
from typing import List, Tuple, Dict

from flask import (
    Flask, render_template, request, redirect, url_for,
    jsonify, abort, send_from_directory
)

from PIL import Image
from moviepy.editor import VideoFileClip
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
BG_DIR = STATIC_DIR / "backgrounds"
OV_DIR = STATIC_DIR / "overlay_input"
TH_DIR = STATIC_DIR / "thumbs"
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

ORDER_JSON = DATA_DIR / "materials_order.json"
OVERRIDES_JSON = DATA_DIR / "material_overrides.json"
RANDOM_TXT = BASE_DIR / "random_texts.txt"

for d in [STATIC_DIR, BG_DIR, OV_DIR, TH_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# 任意: Cloudinaryバックアップ＆accounts保存
try:
    from settings_store import (
        load_accounts as _load_accounts,
        save_accounts as _save_accounts,
        cloud_restore, cloud_backup,
    )
except Exception:
    ACCOUNTS_PATH = DATA_DIR / "accounts.json"
    def _read_json(p: Path, default):
        if p.exists():
            try: return json.loads(p.read_text(encoding="utf-8"))
            except Exception: return default
        return default
    def _write_json(p: Path, obj):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    def _load_accounts():
        data = _read_json(ACCOUNTS_PATH, {"accounts": []})
        return data if isinstance(data, dict) and "accounts" in data else {"accounts": []}
    def _save_accounts(data):
        if not isinstance(data, dict): data = {"accounts": []}
        _write_json(ACCOUNTS_PATH, data)
    def cloud_restore(): return
    def cloud_backup(): return {}

# 生成→Cloudinary→IG投稿のコア
try:
    from poster_core_reel import PosterCoreReel
except Exception:
    PosterCoreReel = None

load_dotenv()
try:
    cloud_restore()
except Exception:
    pass

app = Flask(__name__)

# ---------- util ----------
def list_media(dirpath: Path, exts: Tuple[str, ...]) -> List[str]:
    return sorted([p.name for p in dirpath.iterdir() if p.is_file() and p.suffix.lower() in exts])

def is_video_name(name: str) -> bool:
    return Path(name).suffix.lower() in (".mp4", ".mov", ".m4v", ".webm")

def is_image_name(name: str) -> bool:
    return Path(name).suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")

def load_order() -> List[str]:
    if ORDER_JSON.exists():
        try: return json.loads(ORDER_JSON.read_text("utf-8"))
        except Exception: return []
    return []

def save_order(order: List[str]):
    ORDER_JSON.write_text(json.dumps(order, ensure_ascii=False, indent=2), encoding="utf-8")

def load_overrides() -> Dict[str, str]:
    if OVERRIDES_JSON.exists():
        try:
            d = json.loads(OVERRIDES_JSON.read_text("utf-8"))
            if isinstance(d, dict): return {k: (v if isinstance(v, str) else "") for k, v in d.items()}
        except Exception: pass
    return {}

def save_overrides(js: Dict[str, str]):
    js = {k: (v if isinstance(v, str) else "") for k, v in js.items()}
    OVERRIDES_JSON.write_text(json.dumps(js, ensure_ascii=False, indent=2), encoding="utf-8")

def ensure_thumb(src_path: Path) -> str:
    th_name = src_path.name + ".jpg"
    th_path = TH_DIR / th_name
    if th_path.exists(): return f"static/thumbs/{th_name}"
    try:
        if is_video_name(src_path.name):
            with VideoFileClip(str(src_path)) as clip:
                t = 1.0 if (clip.duration or 0) >= 1.0 else 0.0
                frame = clip.get_frame(t)
            im = Image.fromarray(frame)
        else:
            im = Image.open(src_path).convert("RGB")
        im.thumbnail((320, 320))
        th_path.parent.mkdir(parents=True, exist_ok=True)
        im.save(th_path, "JPEG", quality=85)
        return f"static/thumbs/{th_name}"
    except Exception:
        return ""

def _custom_text_for(filename: str) -> str | None:
    ov = load_overrides()
    txt = (ov.get(filename) or "").strip()
    return txt if txt else None

def _pick_background_for_account(account_no: int) -> Path | None:
    patterns = [f"{account_no}.mp4", f"background{account_no}.mp4", f"bg{account_no}.mp4"]
    for name in patterns:
        p = BG_DIR / name
        if p.exists(): return p
    bg_list = list_media(BG_DIR, (".mp4", ".mov", ".m4v", ".webm"))
    return (BG_DIR / bg_list[0]) if bg_list else None

# ---------- routes ----------
@app.route("/")
def index():
    ov_raw = list_media(OV_DIR, (".mp4", ".mov", ".m4v", ".webm", ".jpg", ".jpeg", ".png", ".webp"))
    order = load_order()
    ordered = [n for n in order if n in ov_raw] + [n for n in ov_raw if n not in order]
    overrides = load_overrides()
    ov_rows = [{"name": n, "thumb": ensure_thumb(OV_DIR / n), "text": overrides.get(n, "")} for n in ordered]
    return render_template("index.html", ov_rows=ov_rows)

@app.route("/static/<path:subpath>")
def static_passthrough(subpath: str):
    target = STATIC_DIR / subpath
    if not target.exists(): abort(404)
    return send_from_directory(STATIC_DIR, subpath)

@app.route("/preview/overlay_input/<filename>")
def preview_overlay(filename: str):
    path = OV_DIR / filename
    if not path.exists(): abort(404)
    rel = f"{OV_DIR.relative_to(BASE_DIR)}/{filename}"
    body = (f'<video controls style="max-width:90vw" src="/{rel}"></video>' if is_video_name(filename)
            else f'<img style="max-width:90vw" src="/{rel}"/>')
    return f"<h3 style='font-family:system-ui'>Preview: {filename}</h3>{body}<p><a href='/'>戻る</a></p>"

@app.route("/upload", methods=["POST"])
def upload():
    target = request.args.get("target", "overlay")
    f = request.files.get("file")
    if not f or not f.filename: return redirect(url_for("index"))
    dest_dir = OV_DIR if target != "backgrounds" else BG_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(f.filename).name
    dest = dest_dir / safe_name
    f.save(dest)
    try: ensure_thumb(dest)
    except Exception: pass
    if dest_dir == OV_DIR:
        order = load_order()
        if safe_name not in order:
            order.append(safe_name)
            save_order(order)
    return redirect(url_for("index"))

@app.route("/materials/sync", methods=["POST"])
def materials_sync():
    js = request.get_json(silent=True) or {}
    order = js.get("order", [])
    texts = js.get("texts", {})
    if isinstance(order, list):
        ex = set(list_media(OV_DIR, (".mp4", ".mov", ".m4v", ".webm", ".jpg", ".jpeg", ".png", ".webp")))
        order = [n for n in order if n in ex]
        save_order(order)
    if isinstance(texts, dict):
        cur = load_overrides()
        for k, v in texts.items(): cur[k] = v if isinstance(v, str) else ""
        save_overrides(cur)
    return jsonify({"ok": True})

@app.route("/materials/delete", methods=["POST"])
def materials_delete():
    filename = request.form.get("filename", "") or (request.json or {}).get("filename", "")
    if not filename: return redirect(url_for("index"))
    src = OV_DIR / Path(filename).name
    if src.exists():
        try: src.unlink()
        except Exception: pass
    th = TH_DIR / (Path(filename).name + ".jpg")
    if th.exists():
        try: th.unlink()
        except Exception: pass
    order = load_order()
    if filename in order:
        save_order([n for n in order if n != filename])
    ov = load_overrides()
    if filename in ov:
        ov.pop(filename, None)
        save_overrides(ov)
    return redirect(url_for("index"))

@app.route("/random_texts_content")
def random_texts_content():
    txt = RANDOM_TXT.read_text("utf-8") if RANDOM_TXT.exists() else ""
    return jsonify({"text": txt})

@app.route("/random_texts", methods=["POST"])
def random_texts_update():
    body = (request.get_json(silent=True) or {}).get("body", "") if request.is_json else request.form.get("body", "")
    RANDOM_TXT.write_text(body, encoding="utf-8")
    return ("", 204)

@app.route("/accounts", methods=["GET"])
def accounts_list():
    return jsonify(_load_accounts())

@app.route("/accounts/upsert", methods=["POST"])
def accounts_upsert():
    data = request.get_json(silent=True) or {}
    no = str(data.get("no", "")).strip()
    if not no: return {"ok": False, "error": "no required"}, 400
    accs = _load_accounts()
    found = False
    for a in accs.get("accounts", []):
        if str(a.get("no", "")) == no:
            a.update({
                "no": no,
                "label": data.get("label", ""),
                "ig_user_id": data.get("ig_user_id", ""),
                "page_id": data.get("page_id", ""),
                "access_token": data.get("access_token", a.get("access_token", "")),
            })
            found = True; break
    if not found:
        accs.setdefault("accounts", []).append({
            "no": no,
            "label": data.get("label", ""),
            "ig_user_id": data.get("ig_user_id", ""),
            "page_id": data.get("page_id", ""),
            "access_token": data.get("access_token", ""),
        })
    _save_accounts(accs)
    return {"ok": True}

@app.route("/accounts/delete", methods=["POST"])
def accounts_delete():
    data = request.get_json(silent=True) or {}
    no = str(data.get("no", "")).strip() or request.form.get("no", "").strip()
    if not no: return {"ok": False, "error": "no required"}, 400
    accs = _load_accounts()
    accs["accounts"] = [a for a in accs.get("accounts", []) if str(a.get("no", "")) != no]
    _save_accounts(accs)
    return {"ok": True}

# ---- 生成→Cloudinary→IG投稿（背景はアカウント番号で自動） ----
@app.route("/generate_and_post", methods=["POST"])
def generate_and_post():
    if PosterCoreReel is None:
        return {"ok": False, "error": "PosterCoreReel not available (import failed)"}, 500
    data = request.get_json(silent=True) or {}
    try:
        account_no = int(str(data.get("account_no")).strip())
    except Exception:
        return {"ok": False, "error": "account_no is required (int)"}, 400
    overlay_name = (data.get("overlay_name") or "").strip()
    if not overlay_name:
        return {"ok": False, "error": "overlay_name is required"}, 400
    ov_path = OV_DIR / overlay_name
    if not ov_path.exists():
        return {"ok": False, "error": f"overlay not found: {overlay_name}"}, 404
    bg_path = _pick_background_for_account(account_no)
    if not bg_path or not bg_path.exists():
        return {"ok": False, "error": "background video not found for this account"}, 404
    custom_txt = _custom_text_for(overlay_name)
    try:
        core = PosterCoreReel()
        media_id = core.post_reel(
            account_no=account_no,
            overlay_path=ov_path,
            background_path=bg_path,
            custom_overlay_text=custom_txt,
            share_to_feed=False,
        )
        return {"ok": True, "media_id": media_id}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}, 500

@app.route("/batch_generate_and_post", methods=["POST"])
def batch_generate_and_post():
    if PosterCoreReel is None:
        return {"ok": False, "error": "PosterCoreReel not available (import failed)"}, 500
    data = request.get_json(silent=True) or {}
    try:
        account_no = int(str(data.get("account_no")).strip())
    except Exception:
        return {"ok": False, "error": "account_no is required (int)"}, 400
    limit = int(data.get("limit", 0) or 0)
    bg_path = _pick_background_for_account(account_no)
    if not bg_path or not bg_path.exists():
        return {"ok": False, "error": "background video not found for this account"}, 404
    order = load_order()
    overlays = [n for n in order if (OV_DIR / n).exists()]
    if limit > 0: overlays = overlays[:limit]
    results = []
    core = PosterCoreReel()
    for name in overlays:
        ov_path = OV_DIR / name
        custom_txt = _custom_text_for(name)
        try:
            media_id = core.post_reel(
                account_no=account_no,
                overlay_path=ov_path,
                background_path=bg_path,
                custom_overlay_text=custom_txt,
                share_to_feed=False,
            )
            results.append({"name": name, "ok": True, "media_id": media_id})
        except Exception as e:
            results.append({"name": name, "ok": False, "error": f"{type(e).__name__}: {e}"})
    return {"ok": True, "results": results}

if __name__ == "__main__":
  app.run(host="0.0.0.0", port=8000, debug=True)
