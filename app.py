# app.py — Flask Web UI (Py3.9 safe) / GUI準拠版
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

# 依存（requirements.txtに moviepy, Pillow 等が入っていること）
from moviepy.editor import VideoFileClip
from PIL import Image

# 自前モジュール（プロジェクト直下）
from settings_store import (
    load_accounts, save_accounts,
    load_overrides, save_overrides,
    load_materials_order, save_materials_order,
    load_random_texts, save_random_texts,
)
from poster_core_reel import PosterCoreReel

# ============ 基本パス ============
BASE_DIR: Path = Path(__file__).resolve().parent
STATIC_DIR: Path = BASE_DIR / "static"
TEMPLATES_DIR: Path = BASE_DIR / "templates"

OVERLAY_DIR: Path = STATIC_DIR / "overlay_input"
THUMBS_DIR: Path = STATIC_DIR / "thumbs"
BACKGROUND_DIR: Path = STATIC_DIR / "backgrounds"
OUTPUT_DIR: Path = STATIC_DIR / "output"

for d in (OVERLAY_DIR, THUMBS_DIR, BACKGROUND_DIR, OUTPUT_DIR, TEMPLATES_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ============ Flask ============
app = Flask(__name__, static_folder=str(STATIC_DIR), template_folder=str(TEMPLATES_DIR))

# アップロード許可拡張子
ALLOWED_EXTS = {
    "jpg", "jpeg", "png", "bmp", "gif", "webp",
    "mp4", "mov", "m4v", "avi", "mkv", "webm"
}

def _is_allowed(filename: str) -> bool:
    ext = filename.rsplit(".", 1)[-1].lower()
    return ext in ALLOWED_EXTS

# ============ サムネ生成 ============
def _thumb_path_for(filename: str) -> Path:
    return THUMBS_DIR / f"{filename}.jpg"

def _ensure_thumb(material_path: Path) -> str:
    """
    素材ファイルのサムネイルを用意して、/static/thumbs/... のURLを返す
    """
    thumb_path = _thumb_path_for(material_path.name)
    if thumb_path.exists():
        return f"/static/thumbs/{thumb_path.name}"

    ext = material_path.suffix.lower().lstrip(".")
    try:
        if ext in {"mp4", "mov", "m4v", "avi", "mkv", "webm"}:
            clip = VideoFileClip(str(material_path))
            frame_path = str(thumb_path)
            # 1秒目でフレーム保存（短い場合は0秒）
            t = 1.0
            try:
                if clip.duration and clip.duration < 1.0:
                    t = 0.0
            except Exception:
                t = 0.0
            clip.save_frame(frame_path, t=t)
            clip.close()
        else:
            # 画像 → そのまま縮小して保存
            with Image.open(str(material_path)) as im:
                im = im.convert("RGB")
                im.thumbnail((480, 480))
                im.save(str(thumb_path), "JPEG", quality=85)
    except Exception:
        # サムネ作成失敗時のフォールバック（透明1px）
        try:
            with Image.new("RGB", (1, 1), (255, 255, 255)) as im:
                im.save(str(thumb_path), "JPEG", quality=80)
        except Exception:
            pass
    return f"/static/thumbs/{thumb_path.name}"

# ============ 素材列挙 ============
def _list_materials() -> List[Dict[str, Any]]:
    overrides: Dict[str, str] = load_overrides()  # filename -> text
    order: List[str] = load_materials_order()     # 並び順（任意）

    files = []
    for p in sorted(OVERLAY_DIR.iterdir()):
        if not p.is_file():
            continue
        if not _is_allowed(p.name):
            continue
        files.append(p.name)

    # 並び順があれば反映（ない素材は末尾）
    if order:
        order_index = {name: i for i, name in enumerate(order)}
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

# ============ 背景選択（アカウント番号に対応） ============
def _pick_background_for_account(account_no: int) -> Optional[Path]:
    """
    優先順位:
      1) backgrounds/{no}.mp4
      2) backgrounds/background{no}.mp4
      3) backgrounds/{no}.mov
      4) backgrounds の先頭の動画
    """
    candidates = [
        BACKGROUND_DIR / f"{account_no}.mp4",
        BACKGROUND_DIR / f"background{account_no}.mp4",
        BACKGROUND_DIR / f"{account_no}.mov",
        BACKGROUND_DIR / f"background{account_no}.mov",
    ]
    for c in candidates:
        if c.exists():
            return c

    # フォールバック：最初に見つかった動画
    for p in BACKGROUND_DIR.iterdir():
        if p.suffix.lower() in {".mp4", ".mov", ".m4v"}:
            return p
    return None

# ============ ルーティング ============
@app.get("/health")
def health() -> Response:
    return jsonify(ok=True)

@app.get("/")
def index():
    accounts = load_accounts().get("accounts", [])
    materials = _list_materials()
    random_texts_body = load_random_texts()
    return render_template(
        "index.html",
        accounts=accounts,
        materials=materials,
        random_texts=random_texts_body
    )

# ---- 素材アップロード ----
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
    # サムネを準備
    _ensure_thumb(save_path)
    return redirect(url_for("index"))

# ---- コメント保存（素材1:1）----
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

# ---- ランダムテキスト 取得/保存 ----
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

# ---- 並び順 保存 ----
@app.post("/api/materials_order")
def api_materials_order():
    try:
        payload = request.get_json(force=True)
        order = payload.get("order", [])
        if not isinstance(order, list):
            order = []
        # 実在するファイルに限定
        existing = {p.name for p in OVERLAY_DIR.iterdir() if p.is_file()}
        order = [n for n in order if n in existing]
        save_materials_order(order)
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500

# ---- 投稿（選択のみ）----
@app.post("/publish_selected")
def publish_selected():
    """
    form:
      account_no: int
      filename: str
      comment: str (空ならランダム)
      share_to_feed: "on" or absent
    """
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

        bg_path = _pick_background_for_account(account_no)
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
        return jsonify(ok=False, error=str(e), tb=traceback.format_exc()), 500

# ---- 投稿（並び順で全部）----
@app.post("/publish_all_ordered")
def publish_all_ordered():
    """
    form:
      account_no: int
      all_accounts: "on" or absent （オンのとき、全アカウントに対して実行）
      share_to_feed: "on" or absent
    """
    try:
        accounts_data = load_accounts().get("accounts", [])
        account_no = int(request.form.get("account_no", "1"))
        all_accounts_flag = request.form.get("all_accounts") == "on"
        share_to_feed = request.form.get("share_to_feed") == "on"

        # 対象アカウントの集合
        target_nos: List[int]
        if all_accounts_flag:
            target_nos = []
            for a in accounts_data:
                try:
                    n = int(str(a.get("no", "1")))
                    target_nos.append(n)
                except Exception:
                    continue
            target_nos = sorted(set(target_nos))
            if not target_nos:
                target_nos = [account_no]
        else:
            target_nos = [account_no]

        # 並び順
        order = load_materials_order()
        if not order:
            # 並び順が未設定ならファイル名昇順
            order = []
            for p in sorted(OVERLAY_DIR.iterdir()):
                if p.is_file() and _is_allowed(p.name):
                    order.append(p.name)

        overrides = load_overrides()
        core = PosterCoreReel()

        results: List[Dict[str, Any]] = []
        for no in target_nos:
            bg = _pick_background_for_account(no)
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

# ---- 静的ファイルの直接配信（必要に応じて）----
@app.get("/static/<path:filename>")
def static_files(filename: str):
    return send_from_directory(str(STATIC_DIR), filename, as_attachment=False)

# ============ エラービュー（保険） ============
@app.get("/__app_error")
def app_error_view():
    # ここは import guard 方式をやめたので、通常は使われませんが保険で残します
    return Response("No app.py import error captured.", mimetype="text/plain", status=200)

# ============ ローカル起動 ============
if __name__ == "__main__":
    # ローカル確認用（Renderでは使われません）
    app.run(host="0.0.0.0", port=8000, debug=True)
