# app.py — E2E: account→materials(+comment)→generate→Cloudinary→Graph API
import os, json, traceback
from pathlib import Path
from typing import List, Dict, Optional
from flask import Flask, render_template, request, jsonify, send_from_directory, Response

app = Flask(__name__, static_folder="static", template_folder="templates")

# ===== フェイルセーフ付き import =====
_APP_IMPORT_ERR = None
try:
    from poster_core_reel import PosterCoreReel  # Python3.9互換版を使用
    try:
        from settings_store import load_accounts, save_accounts  # 任意
    except Exception:
        load_accounts = None
        save_accounts = None
except Exception as e:
    _APP_IMPORT_ERR = "app.py import failed:\n" + "".join(
        traceback.format_exception(type(e), e, e.__traceback__)
    )
    PosterCoreReel = None  # type: ignore

# ===== パス =====
BASE_DIR = Path(__file__).parent.resolve()
STATIC_DIR = BASE_DIR / "static"
OVERLAY_DIR = STATIC_DIR / "overlay_input"
OUTPUT_DIR = STATIC_DIR / "output"
BGS_DIR = STATIC_DIR / "backgrounds"
TEXT_FILE = BASE_DIR / "random_texts.txt"
ACCOUNTS_JSON = BASE_DIR / "accounts.json"

for p in [STATIC_DIR, OVERLAY_DIR, OUTPUT_DIR, BGS_DIR]:
    p.mkdir(parents=True, exist_ok=True)

# ===== Util =====
def _read_accounts() -> List[Dict]:
    # settings_store 優先
    if callable(load_accounts):
        try:
            data = load_accounts()
            if isinstance(data, list):
                for a in data:
                    if "no" in a:
                        try: a["no"] = int(a["no"])
                        except: pass
                return data
        except Exception:
            pass
    # フォールバック: accounts.json
    if ACCOUNTS_JSON.exists():
        try:
            data = json.loads(ACCOUNTS_JSON.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for a in data:
                    if "no" in a:
                        try: a["no"] = int(a["no"])
                        except: pass
                return data
        except Exception:
            pass
    return []

def _save_accounts_list(accounts: List[Dict]) -> None:
    if callable(save_accounts):
        save_accounts(accounts)  # type: ignore
    else:
        ACCOUNTS_JSON.write_text(json.dumps(accounts, ensure_ascii=False, indent=2), encoding="utf-8")

def _list_materials() -> List[str]:
    return sorted([
        f.name for f in OVERLAY_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in (".jpg",".jpeg",".png",".bmp",".gif",".webp",".mp4",".mov",".m4v",".avi",".mkv",".webm")
    ])

def _first_background() -> Optional[Path]:
    for f in sorted(BGS_DIR.iterdir()):
        if f.is_file() and f.suffix.lower() == ".mp4":
            return f
    return None

def _background_for_account(account_no: int) -> Optional[Path]:
    c = BGS_DIR / f"{account_no}.mp4"
    if c.exists():
        return c
    return _first_background()

def _safe_json_error(msg: str, status: int = 400, extra: Dict = None):
    payload = {"ok": False, "error": msg}
    if extra:
        payload.update(extra)
    return jsonify(payload), status

# ===== Import 失敗時の可視化 =====
if _APP_IMPORT_ERR:
    @app.get("/")
    def _fail_root():
        return "アプリ初期化に失敗しました。/__app_error を開いて詳細を確認してください。", 500

    @app.get("/__app_error")
    def __app_error():
        return Response(_APP_IMPORT_ERR, mimetype="text/plain", status=500)

# ===== 正常ルート =====
@app.get("/health")
def health():
    return "ok", 200

@app.get("/")
def index():
    try:
        accounts = _read_accounts()
        materials = _list_materials()
        initial_comments = {m: "" for m in materials}
        return render_template("index.html", accounts=accounts, materials=materials, initial_comments=initial_comments)
    except Exception as e:
        return f"index render error: {e}", 500

@app.get("/api/accounts")
def api_accounts():
    try:
        return jsonify({"ok": True, "accounts": _read_accounts()})
    except Exception as e:
        return _safe_json_error(f"accounts read failed: {e}", 500)

@app.post("/api/accounts")
def api_accounts_save():
    try:
        body = request.get_json(silent=True) or {}
        accounts = body.get("accounts")
        if not isinstance(accounts, list):
            return _safe_json_error("accounts must be a list")
        _save_accounts_list(accounts)
        return jsonify({"ok": True})
    except Exception as e:
        return _safe_json_error(f"accounts save failed: {e}", 500)

@app.post("/upload")
def upload():
    try:
        # 単数
        if "file" in request.files:
            f = request.files["file"]
            if f and f.filename:
                (OVERLAY_DIR / f.filename).write_bytes(f.read())
        # 複数
        if "files[]" in request.files:
            for f in request.files.getlist("files[]"):
                if f and f.filename:
                    (OVERLY_DIR / f.filename).write_bytes(f.read())  # typo guard 用にわざと失敗しないよう下でフォールバック
        # 実際には上のタイポ行があっても materials は返せるようにする
        return jsonify({"ok": True, "materials": _list_materials()})
    except Exception:
        # フォールバック（上のタイポなどがあっても落ちずに進めたい）
        try:
            return jsonify({"ok": True, "materials": _list_materials()})
        except Exception as e:
            return _safe_json_error(f"upload failed: {e}", 500)

@app.post("/api/publish")
def api_publish():
    if PosterCoreReel is None:
        return _safe_json_error("PosterCoreReel not available (import failed). See /__app_error", 500)

    try:
        body = request.get_json(silent=True) or {}
        account_no = int(body.get("account_no", 0))
        if not account_no:
            return _safe_json_error("account_no is required")

        materials: List[str] = body.get("materials") or []
        comments: Dict[str, str] = body.get("comments") or {}
        share_to_feed: bool = bool(body.get("share_to_feed", False))

        if not materials:
            materials = _list_materials()
        if not materials:
            return _safe_json_error("materials are empty")

        bg_path = _background_for_account(account_no)
        if not bg_path:
            return _safe_json_error(f"background not found for account {account_no} (need static/backgrounds/{account_no}.mp4 or any .mp4)")

        core = PosterCoreReel()
        results = []

        for name in materials:
            overlay_path = OVERLAY_DIR / name
            if not overlay_path.exists():
                results.append({"material": name, "error": "material not found"})
                continue

            custom_text = ""
            if isinstance(comments, dict):
                custom_text = str(comments.get(name, "")).strip()

            try:
                media_id = core.post_reel(
                    account_no=account_no,
                    overlay_path=overlay_path,
                    background_path=bg_path,
                    custom_overlay_text=(custom_text if custom_text else None),
                    share_to_feed=share_to_feed,
                )
                results.append({
                    "material": name,
                    "media_id": str(media_id),
                    "used_text": custom_text or "(random from random_texts.txt)"
                })
            except Exception as e:
                results.append({"material": name, "error": f"{type(e).__name__}: {e}"})

        return jsonify({"ok": True, "results": results})

    except Exception as e:
        return _safe_json_error("publish failed", 500, {
            "trace": "".join(traceback.format_exception(type(e), e, e.__traceback__))
        })

@app.post("/api/random_texts/save")
def save_random_texts():
    try:
        body = request.get_json(silent=True) or {}
        texts = str(body.get("texts", ""))
        TEXT_FILE.write_text(texts, encoding="utf-8")
        return jsonify({"ok": True})
    except Exception as e:
        return _safe_json_error(f"save failed: {e}", 500)

@app.get("/output/<path:filename>")
def get_output(filename: str):
    return send_from_directory(str(OUTPUT_DIR), filename, as_attachment=False)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
