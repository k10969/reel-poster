# app.py  — Python 3.9 互換 / 元GUI仕様
import os
import json
from pathlib import Path
from typing import Optional, List, Dict, Tuple

from flask import (
    Flask, render_template, request, redirect, url_for,
    jsonify, abort, send_from_directory
)

from PIL import Image
from moviepy.editor import VideoFileClip
from dotenv import load_dotenv

# ----------------- パス設定 -----------------
BASE_DIR: Path = Path(__file__).resolve().parent
STATIC_DIR: Path = BASE_DIR / "static"
BG_DIR: Path = STATIC_DIR / "backgrounds"
OV_DIR: Path = STATIC_DIR / "overlay_input"
TH_DIR: Path = STATIC_DIR / "thumbs"

# 元ツールと同じ場所（プロジェクト直下）に保存
ORDER_JSON: Path = BASE_DIR / "materials_order.json"
OVERRIDES_JSON: Path = BASE_DIR / "material_overrides.json"
RANDOM_TXT: Path = BASE_DIR / "random_texts.txt"

for d in (STATIC_DIR, BG_DIR, OV_DIR, TH_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ----------------- 設定ストア（存在すれば利用） -----------------
try:
    from settings_store import (
        load_accounts as _load_accounts,
        save_accounts as _save_accounts,
        cloud_restore, cloud_backup,
    )
except Exception:
    # フォールバック: 単純な json 保存
    ACCOUNTS_PATH = BASE_DIR / "accounts.json"

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
        return data if isinstance(data, dict) and "accounts" in data else {"accounts": []}

    def _save_accounts(data):
        if not isinstance(data, dict):
            data = {"accounts": []}
        _write_json(ACCOUNTS_PATH, data)

    def cloud_restore():
        return

    def cloud_backup():
        return {}

# ----------------- 生成→Cloudinary→IG投稿コア -----------------
try:
    # あなたのコア（poster_core_reel.py）を使います
    from poster_core_reel import PosterCoreReel
except Exception:
    PosterCoreReel = None  # 起動は通す。/post 叩いたら 500 を返す

load_dotenv()
try:
    # クラウドから設定復元（実装されていれば）
    cloud_restore()
except Exception:
    pass

app = Flask(__name__)

# ----------------- ユーティリティ -----------------
def list_media(dirpath: Path, exts: Tuple[str, ...]) -> List[str]:
    items = []
    for p in dirpath.iterdir():
        if p.is_file() and p.suffix.lower() in exts:
            items.append(p.name)
    return sorted(items)

def is_video_name(name: str) -> bool:
    return Path(name).suffix.lower() in (".mp4", ".mov", ".m4v", ".webm")

def is_image_name(name: str) -> bool:
    return Path(name).suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")

def load_order() -> List[str]:
    if ORDER_JSON.exists():
        try:
            arr = json.loads(ORDER_JSON.read_text("utf-8"))
            return arr if isinstance(arr, list) else []
        except Exception:
            return []
    return []

def save_order(order: List[str]) -> None:
    ORDER_JSON.write_text(json.dumps(order, ensure_ascii=False, indent=2), encoding="utf-8")

def load_overrides() -> Dict[str, str]:
    if OVERRIDES_JSON.exists():
        try:
            d = json.loads(OVERRIDES_JSON.read_text("utf-8"))
            if isinstance(d, dict):
                # 文字列以外は空扱い
                return {str(k): (v if isinstance(v, str) else "") for k, v in d.items()}
        except Exception:
            pass
    return {}

def save_overrides(js: Dict[str, str]) -> None:
    js = {str(k): (v if isinstance(v, str) else "") for k, v in js.items()}
    OVERRIDES_JSON.write_text(json.dumps(js, ensure_ascii=False, indent=2), encoding="utf-8")

def ensure_thumb(src_path: Path) -> str:
    """
    サムネを作って /static/thumbs/<filename>.jpg を返す（失敗時は ""）
    """
    th_name = src_path.name + ".jpg"
    th_path = TH_DIR / th_name
    if th_path.exists():
        return f"static/thumbs/{th_name}"
    try:
        if is_video_name(src_path.name):
            with VideoFileClip(str(src_path)) as clip:
                t = 1.0 if (clip.duration or 0.0) >= 1.0 else 0.0
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

def _custom_text_for(filename: str) -> Optional[str]:
    """
    各素材に対するテキスト上書きを返す。空なら None（⇒ コア側で random_texts.txt を使用）
    """
    ov = load_overrides()
    txt = (ov.get(filename) or "").strip()
    return txt if txt else None

def _pick_background_for_account(account_no: int) -> Optional[Path]:
    """
    背景はアカウント番号に自動連動。
    優先： '1.mp4' → 'background1.mp4' → 'bg1.mp4' → 背景フォルダの先頭
    """
    patterns = [f"{account_no}.mp4", f"background{account_no}.mp4", f"bg{account_no}.mp4"]
    for name in patterns:
        p = BG_DIR / name
        if p.exists():
            return p
    bg_list = list_media(BG_DIR, (".mp4", ".mov", ".m4v", ".webm"))
    return (BG_DIR / bg_list[0]) if bg_list else None

# ----------------- 画面 -----------------
@app.route("/")
def index():
    ov_raw = list_media(OV_DIR, (".mp4", ".mov", ".m4v", ".webm", ".jpg", ".jpeg", ".png", ".webp"))
    order = load_order()
    # 並び順 + 未登録分を後ろに
    ordered = [n for n in order if n in ov_raw] + [n for n in ov_raw if n not in order]
    overrides = load_overrides()
    ov_rows = [{"name": n, "thumb": ensure_thumb(OV_DIR / n), "text": overrides.get(n, "")} for n in ordered]
    return render_template("index.html", ov_rows=ov_rows)

# 静的ファイル直配信（/static/〜）
@app.route("/static/<path:subpath>")
def static_passthrough(subpath: str):
    target = STATIC_DIR / subpath
    if not target.exists():
        abort(404)
    return send_from_directory(STATIC_DIR, subpath)

# 素材プレビュー（別タブ）
@app.route("/preview/overlay_input/<filename>")
def preview_overlay(filename: str):
    path = OV_DIR / filename
    if not path.exists():
        abort(404)
    rel = f"{OV_DIR.relative_to(BASE_DIR)}/{filename}"
    body = (f'<video controls style="max-width:90vw" src="/{rel}"></video>'
            if is_video_name(filename)
            else f'<img style="max-width:90vw" src="/{rel}"/>')
    return f"<h3 style='font-family:system-ui'>Preview: {filename}</h3>{body}<p><a href='/'>戻る</a></p>"

# ----------------- CRUD API -----------------
# 素材アップロード（iPhoneから）
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
    try:
        ensure_thumb(dest)
    except Exception:
        pass
    # 素材なら並び順の末尾へ
    if dest_dir == OV_DIR:
        order = load_order()
        if safe_name not in order:
            order.append(safe_name)
            save_order(order)
    return redirect(url_for("index"))

# 並び順＆テキストを自動保存
@app.route("/materials/sync", methods=["POST"])
def materials_sync():
    js = request.get_json(silent=True) or {}
    order = js.get("order", [])
    texts = js.get("texts", {})
    # 並び順
    if isinstance(order, list):
        ex = set(list_media(OV_DIR, (".mp4", ".mov", ".m4v", ".webm", ".jpg", ".jpeg", ".png", ".webp")))
        order = [n for n in order if n in ex]
        save_order(order)
    # 上書きテキスト
    if isinstance(texts, dict):
        cur = load_overrides()
        for k, v in texts.items():
            cur[str(k)] = v if isinstance(v, str) else ""
        save_overrides(cur)
    return jsonify({"ok": True})

# 素材削除
@app.route("/materials/delete", methods=["POST"])
def materials_delete():
    filename = request.form.get("filename", "") or (request.get_json(silent=True) or {}).get("filename", "")
    if not filename:
        return redirect(url_for("index"))
    src = OV_DIR / Path(filename).name
    if src.exists():
        try:
            src.unlink()
        except Exception:
            pass
    th = TH_DIR / (Path(filename).name + ".jpg")
    if th.exists():
        try:
            th.unlink()
        except Exception:
            pass
    order = load_order()
    if filename in order:
        save_order([n for n in order if n != filename])
    ov = load_overrides()
    if filename in ov:
        ov.pop(filename, None)
        save_overrides(ov)
    return redirect(url_for("index"))

# ランダムテキスト取得/保存
@app.route("/random_texts_content")
def random_texts_content():
    txt = RANDOM_TXT.read_text("utf-8") if RANDOM_TXT.exists() else ""
    return jsonify({"text": txt})

@app.route("/random_texts", methods=["POST"])
def random_texts_update():
    body = (request.get_json(silent=True) or {}).get("body", "") if request.is_json else request.form.get("body", "")
    RANDOM_TXT.write_text(body, encoding="utf-8")
    return ("", 204)

# アカウント一覧/追加/削除（画面から編集可能）
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

# ----------------- 投稿ディスパッチ（元GUI仕様） -----------------
@app.route("/post", methods=["POST"])
def post_dispatch():
    """
    JSON:
    {
      "overlay_names": ["IMG_1234.jpg", ...]  # 行選択があるときはその配列、無ければ空でOK（サーバ側が全件にする）
      "all_accounts": true/false,             # 全アカウント（分散投稿）
      "account_no": "1"                       # all_accounts=false の時だけ必須
    }
    動作:
      - overlay_names が空 → materials_order.json の順で全件
      - all_accounts=true → 登録済みの全アカウントに対し順番に投稿
      - 背景はアカウント番号に連動（1→1.mp4 / background1.mp4 / bg1.mp4 / 先頭フォールバック）
      - 各素材のテキストは material_overrides.json を優先、空なら core 側で random_texts.txt を用いる
    """
    if PosterCoreReel is None:
        return {"ok": False, "error": "PosterCoreReel not available (import failed)"}, 500

    data = request.get_json(silent=True) or {}
    overlay_names = data.get("overlay_names") or []
    all_accounts = bool(data.get("all_accounts", False))

    # 並び順を採用
    if not overlay_names:
        order = load_order()
        overlay_names = [n for n in order if (OV_DIR / n).exists()]
    else:
        overlay_names = [str(n) for n in overlay_names if (OV_DIR / str(n)).exists()]

    if not overlay_names:
        return {"ok": False, "error": "no overlays to post"}, 400

    core = PosterCoreReel()
    results: List[Dict[str, str]] = []

    def _post_for_account(account_no: int) -> None:
        bg = _pick_background_for_account(account_no)
        if not bg or not bg.exists():
            results.append({"account_no": str(account_no), "ok": False, "error": "background not found"})
            return
        for name in overlay_names:
            ov = OV_DIR / name
            custom = _custom_text_for(name)
            try:
                media_id = core.post_reel(
                    account_no=account_no,
                    overlay_path=ov,
                    background_path=bg,
                    custom_overlay_text=custom,
                    share_to_feed=False,
                )
                results.append({"account_no": str(account_no), "name": name, "ok": True, "media_id": str(media_id)})
            except Exception as e:
                results.append({"account_no": str(account_no), "name": name, "ok": False, "error": f"{type(e).__name__}: {e}"})

    if all_accounts:
        accs = _load_accounts().get("accounts", [])
        # 番号昇順に処理
        def parse_no(x):
            try:
                return int(str(x.get("no", "")).strip())
            except Exception:
                return 0
        for acc in sorted(accs, key=parse_no):
            no = parse_no(acc)
            if no > 0:
                _post_for_account(no)
    else:
        try:
            account_no = int(str(data.get("account_no")).strip())
        except Exception:
            return {"ok": False, "error": "account_no required when all_accounts=false"}, 400
        _post_for_account(account_no)

    return {"ok": True, "results": results}

# ----------------- 起動 -----------------
if __name__ == "__main__":
    # ローカル確認用
    app.run(host="0.0.0.0", port=8000, debug=True)
