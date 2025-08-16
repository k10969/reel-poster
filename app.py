import os
import json
from pathlib import Path
from typing import List, Tuple, Dict

from flask import (
    Flask, render_template, request, redirect, url_for,
    jsonify, abort, send_from_directory
)

# 画像/動画（サムネ生成に使用）
from PIL import Image
from moviepy.editor import VideoFileClip

# .env（RenderのEnvironment変数も拾える）
from dotenv import load_dotenv

# ==============================
#  パス/ディレクトリ 初期化
# ==============================
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
BG_DIR = STATIC_DIR / "backgrounds"
OV_DIR = STATIC_DIR / "overlay_input"
OUT_DIR = STATIC_DIR / "output"
TH_DIR = STATIC_DIR / "thumbs"
FONT_FILE = STATIC_DIR / "fonts" / "keifont.ttf"   # 使う場合は同梱

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

ORDER_JSON = DATA_DIR / "materials_order.json"      # 並び順
OVERRIDES_JSON = DATA_DIR / "material_overrides.json"  # { filename: text }
RANDOM_TXT = BASE_DIR / "random_texts.txt"          # ランダムテキスト

for d in [STATIC_DIR, BG_DIR, OV_DIR, OUT_DIR, TH_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ==============================
#  設定ストア（任意：無ければローカルにフォールバック）
# ==============================
try:
    from settings_store import (
        load_accounts as _load_accounts,
        save_accounts as _save_accounts,
        cloud_restore, cloud_backup,
    )
except Exception:
    # settings_store.py が無い場合の簡易実装（data/accounts.json）
    ACCOUNTS_PATH = DATA_DIR / "accounts.json"

    def _read_json(p: Path, default):
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return default
        return default

    def _write_json(p: Path, obj):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_accounts():
        data = _read_json(ACCOUNTS_PATH, {"accounts": []})
        if not isinstance(data, dict) or "accounts" not in data:
            data = {"accounts": []}
        return data

    def _save_accounts(data):
        if not isinstance(data, dict):
            data = {"accounts": []}
        _write_json(ACCOUNTS_PATH, data)

    def cloud_restore():
        # 何もしない（オプション機能）
        return

    def cloud_backup():
        # 何もしない（オプション機能）
        return {}

# ==============================
#  Flask / 環境読み込み
# ==============================
load_dotenv()
try:
    cloud_restore()  # Cloudinary raw からの復元（任意機能）
except Exception:
    pass

app = Flask(__name__)

# ==============================
#  ユーティリティ
# ==============================
def list_media(dirpath: Path, exts: Tuple[str, ...]) -> List[str]:
    return sorted([p.name for p in dirpath.iterdir() if p.is_file() and p.suffix.lower() in exts])

def is_video_name(name: str) -> bool:
    return Path(name).suffix.lower() in (".mp4", ".mov", ".m4v", ".webm")

def is_image_name(name: str) -> bool:
    return Path(name).suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")

def load_order() -> List[str]:
    if ORDER_JSON.exists():
        try:
            return json.loads(ORDER_JSON.read_text("utf-8"))
        except Exception:
            return []
    return []

def save_order(order: List[str]):
    ORDER_JSON.write_text(json.dumps(order, ensure_ascii=False, indent=2), encoding="utf-8")

def load_overrides() -> Dict[str, str]:
    if OVERRIDES_JSON.exists():
        try:
            data = json.loads(OVERRIDES_JSON.read_text("utf-8"))
            if isinstance(data, dict):
                # valueは文字列想定
                return {k: (v if isinstance(v, str) else "") for k, v in data.items()}
        except Exception:
            pass
    return {}

def save_overrides(js: Dict[str, str]):
    # valueは文字列に正規化
    norm = {k: (v if isinstance(v, str) else "") for k, v in js.items()}
    OVERRIDES_JSON.write_text(json.dumps(norm, ensure_ascii=False, indent=2), encoding="utf-8")

def ensure_thumb(src_path: Path) -> str:
    """
    動画は1秒目（無ければ0秒）を、画像はそのまま縮小して thumbnail を生成。
    返り値: Flask で参照できる 'static/thumbs/<name>.jpg' 相対パス。失敗時は ""。
    """
    th_name = src_path.name + ".jpg"
    th_path = TH_DIR / th_name
    if th_path.exists():
        return f"static/thumbs/{th_name}"
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

# ==============================
#  ルーティング
# ==============================
@app.route("/")
def index():
    # overlay_input の素材一覧（拡張子フィルタ）
    ov_raw = list_media(OV_DIR, (".mp4", ".mov", ".m4v", ".webm", ".jpg", ".jpeg", ".png", ".webp"))

    # 並べ替え適用（未知のものは末尾）
    order = load_order()
    ordered = [n for n in order if n in ov_raw] + [n for n in ov_raw if n not in order]

    # テキスト上書き
    overrides = load_overrides()

    ov_rows = []
    for name in ordered:
        ov_rows.append({
            "name": name,                          # UIでは出さないが内部キーとして保持
            "thumb": ensure_thumb(OV_DIR / name),  # サムネ
            "text": overrides.get(name, ""),       # 空ならランダム採用
        })

    # 出力一覧（必要に応じて使う）
    outs_rows = list_media(OUT_DIR, (".mp4", ".mov", ".m4v", ".webm"))

    return render_template(
        "index.html",
        ov_rows=ov_rows,
        outs_rows=outs_rows,
    )

# 静的配信用の明示ルート（/static/<path>）
@app.route("/static/<path:subpath>")
def static_passthrough(subpath: str):
    target = STATIC_DIR / subpath
    if not target.exists():
        abort(404)
    return send_from_directory(STATIC_DIR, subpath)

# プレビュー（素材）
@app.route("/preview/overlay_input/<filename>")
def preview_overlay(filename: str):
    path = OV_DIR / filename
    if not path.exists():
        abort(404)
    rel = f"{OV_DIR.relative_to(BASE_DIR)}/{filename}"
    body = (
        f'<video controls style="max-width:90vw" src="/{rel}"></video>'
        if is_video_name(filename)
        else f'<img style="max-width:90vw" src="/{rel}"/>'
    )
    return f"""
    <h2 style='font-family:system-ui'>Preview: {filename}</h2>
    {body}
    <p><a href="/">戻る</a></p>
    """

# ------------------------------
#  アップロード（iPhoneから）
# ------------------------------
@app.route("/upload", methods=["POST"])
def upload():
    target = request.args.get("target", "overlay")
    f = request.files.get("file")
    if not f or not f.filename:
        return redirect(url_for("index"))

    dest_dir = OV_DIR if target != "backgrounds" else BG_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(f.filename).name
    dest = dest_dir / safe_name
    f.save(dest)

    # サムネ生成（失敗は無視）
    try:
        ensure_thumb(dest)
    except Exception:
        pass

    # 新規ファイルは並びの末尾へ
    if dest_dir == OV_DIR:
        order = load_order()
        if safe_name not in order:
            order.append(safe_name)
            save_order(order)

    return redirect(url_for("index"))

# -----------------------------------
#  並べ替え＆各行テキストの自動保存
# -----------------------------------
@app.route("/materials/sync", methods=["POST"])
def materials_sync():
    js = request.get_json(silent=True) or {}
    order = js.get("order", [])
    texts = js.get("texts", {})

    # 並び順
    if isinstance(order, list):
        # 実在するものだけに限定
        ex = set(list_media(OV_DIR, (".mp4", ".mov", ".m4v", ".webm", ".jpg", ".jpeg", ".png", ".webp")))
        order = [n for n in order if n in ex]
        save_order(order)

    # テキスト上書き
    if isinstance(texts, dict):
        cur = load_overrides()
        for k, v in texts.items():
            cur[k] = v if isinstance(v, str) else ""
        save_overrides(cur)

    return jsonify({"ok": True})

# -----------------------------------
#  素材の削除（サムネ/メタも一緒に）
# -----------------------------------
@app.route("/materials/delete", methods=["POST"])
def materials_delete():
    filename = request.form.get("filename", "") or (request.json or {}).get("filename", "")
    if not filename:
        return redirect(url_for("index"))
    # 元ファイル
    src = OV_DIR / Path(filename).name
    if src.exists():
        try:
            src.unlink()
        except Exception:
            pass
    # サムネ
    th = TH_DIR / (Path(filename).name + ".jpg")
    if th.exists():
        try:
            th.unlink()
        except Exception:
            pass
    # 並び順から除外
    order = load_order()
    if filename in order:
        order = [n for n in order if n != filename]
        save_order(order)
    # テキスト上書きからも除外
    ov = load_overrides()
    if filename in ov:
        ov.pop(filename, None)
        save_overrides(ov)

    return redirect(url_for("index"))

# -----------------------------------
#  ランダムテキスト：表示 & 自動保存
# -----------------------------------
@app.route("/random_texts_content")
def random_texts_content():
    txt = ""
    if RANDOM_TXT.exists():
        txt = RANDOM_TXT.read_text("utf-8")
    return jsonify({"text": txt})

@app.route("/random_texts", methods=["POST"])
def random_texts_update():
    # JSON でも form でもOK
    if request.is_json:
        body = (request.get_json(silent=True) or {}).get("body", "")
    else:
        body = request.form.get("body", "")
    RANDOM_TXT.write_text(body, encoding="utf-8")
    return ("", 204)  # 自動保存なので画面遷移なし

# -----------------------------------
#  アカウントAPI（UIのセレクタ用）
# -----------------------------------
@app.route("/accounts", methods=["GET"])
def accounts_list():
    return jsonify(_load_accounts())

@app.route("/accounts/upsert", methods=["POST"])
def accounts_upsert():
    data = request.get_json(silent=True) or {}
    no = str(data.get("no", "")).strip()
    if not no:
        return {"ok": False, "error": "no required"}, 400

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
            found = True
            break
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
    if not no:
        return {"ok": False, "error": "no required"}, 400
    accs = _load_accounts()
    accs["accounts"] = [a for a in accs.get("accounts", []) if str(a.get("no", "")) != no]
    _save_accounts(accs)
    return {"ok": True}

# ==============================
#  エントリポイント
# ==============================
if __name__ == "__main__":
    # ローカル開発用
    app.run(host="0.0.0.0", port=8000, debug=True)
