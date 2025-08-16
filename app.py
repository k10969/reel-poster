import os
import io
import json
import random
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

from flask import (
    Flask, render_template, request, redirect, url_for,
    send_from_directory, jsonify, abort
)

# 画像/動画処理
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import VideoFileClip, CompositeVideoClip, ImageClip, vfx

# 環境・外部連携
from dotenv import load_dotenv
from cloudinary_helper import upload_media_local
from graph_publisher import ig_post_now
from settings_store import (
    load_accounts as _load_accounts,
    save_accounts as _save_accounts,
    cloud_backup, cloud_restore
)

# =======================================
# パス/ディレクトリ初期化
# =======================================
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
BG_DIR = STATIC_DIR / "backgrounds"
OV_DIR = STATIC_DIR / "overlay_input"
OUT_DIR = STATIC_DIR / "output"
TH_DIR = STATIC_DIR / "thumbs"
FONT_FILE = STATIC_DIR / "fonts" / "keifont.ttf"

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

ORDER_JSON = DATA_DIR / "materials_order.json"
OVERRIDES_JSON = DATA_DIR / "material_overrides.json"
RANDOM_TXT = BASE_DIR / "random_texts.txt"

for d in [BG_DIR, OV_DIR, OUT_DIR, TH_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# =======================================
# Flask & 環境
# =======================================
load_dotenv()     # Render の Environment もここで読み込まれる
try:
    cloud_restore()  # Cloudinary の raw（accounts/settings）から復元（存在すれば）
except Exception:
    # 復元失敗は致命的ではないので無視
    pass

app = Flask(__name__)

# =======================================
# ユーティリティ
# =======================================
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

def load_overrides() -> dict:
    if OVERRIDES_JSON.exists():
        try:
            return json.loads(OVERRIDES_JSON.read_text("utf-8"))
        except Exception:
            return {}
    return {}

def save_overrides(js: dict):
    OVERRIDES_JSON.write_text(json.dumps(js, ensure_ascii=False, indent=2), encoding="utf-8")

def random_line() -> str:
    if RANDOM_TXT.exists():
        lines = [l.strip() for l in RANDOM_TXT.read_text("utf-8").splitlines() if l.strip()]
        if lines:
            return random.choice(lines)
    return ""

def ensure_thumb(src_path: Path) -> str:
    """
    動画は1秒目を、画像はそのまま縮小して thumbnail を生成。
    返り値: Flask から参照できる 'static/thumbs/xxx.jpg' 相対パス。失敗時は ""。
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

def text_to_image(
    text: str,
    font_size: int = 64,
    color: str = "#ffffff",
    stroke_width: int = 4,
    stroke_color: str = "#000000",
    padding: int = 16,
) -> Image.Image:
    """
    同梱フォント（static/fonts/keifont.ttf）を使って、縁取りテキスト画像を生成
    """
    # フォント決定
    if FONT_FILE.exists():
        font = ImageFont.truetype(str(FONT_FILE), font_size)
    else:
        font = ImageFont.load_default()

    # サイズ計測
    temp_img = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    draw = ImageDraw.Draw(temp_img)
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]

    # 実画像
    img = Image.new("RGBA", (w + padding * 2, h + padding * 2), (0, 0, 0, 0))
    draw2 = ImageDraw.Draw(img)
    draw2.text(
        (padding, padding),
        text,
        font=font,
        fill=color,
        stroke_width=stroke_width,
        stroke_fill=stroke_color,
    )
    return img

def map_pos(pos: str, base_w: int, base_h: int, clip_w: int, clip_h: int) -> Tuple[int, int]:
    """
    pos: 'top-right' | 'top-left' | 'bottom-right' | 'bottom-left' | 'center'
    を左上座標(x,y)に変換
    """
    if pos == "top-right":
        return (base_w - clip_w, 0)
    if pos == "top-left":
        return (0, 0)
    if pos == "bottom-right":
        return (base_w - clip_w, base_h - clip_h)
    if pos == "bottom-left":
        return (0, base_h - clip_h)
    # center
    return ((base_w - clip_w) // 2, (base_h - clip_h) // 2)

# =======================================
# ルーティング
# =======================================
@app.route("/")
def index():
    # 背景一覧（動画）
    bg_list = list_media(BG_DIR, (".mp4", ".mov", ".m4v", ".webm"))
    bg_rows = [(name, ensure_thumb(BG_DIR / name)) for name in bg_list]

    # 素材一覧（画像/動画）
    ov_raw = list_media(OV_DIR, (".mp4", ".mov", ".m4v", ".webm", ".jpg", ".jpeg", ".png", ".webp"))
    order = load_order()
    overrides = load_overrides()
    # 順序に従って並べ替え（未知のものは末尾）
    ordered = [n for n in order if n in ov_raw] + [n for n in ov_raw if n not in order]
    ov_rows = []
    for name in ordered:
        ov_rows.append({
            "name": name,
            "thumb": ensure_thumb(OV_DIR / name),
            "text": overrides.get(name, ""),
        })

    # 出力一覧（動画）
    outs_rows = list_media(OUT_DIR, (".mp4", ".mov", ".m4v", ".webm"))

    return render_template(
        "index.html",
        bg_rows=bg_rows,
        ov_rows=ov_rows,
        outs_rows=outs_rows,
    )

@app.route("/random_texts")
def random_texts_view():
    txt = ""
    if RANDOM_TXT.exists():
        txt = RANDOM_TXT.read_text("utf-8")
    return f"""
    <h2>random_texts.txt</h2>
    <form method="post" action="{url_for('random_texts_update')}">
    <textarea name="body" style="width:96%;height:60vh;">{txt}</textarea><br>
    <button>保存</button>
    </form>
    <p><a href="/">戻る</a></p>
    """

@app.route("/random_texts", methods=["POST"])
def random_texts_update():
    body = request.form.get("body", "")
    RANDOM_TXT.write_text(body, encoding="utf-8")
    return redirect(url_for("random_texts_view"))

@app.route("/static/<path:subpath>")
def static_passthrough(subpath):
    # 既定の static と同じだが、相対で配りやすくするため明示
    target = STATIC_DIR / subpath
    if not target.exists():
        abort(404)
    return send_from_directory(STATIC_DIR, subpath)

@app.route("/preview/<kind>/<filename>")
def preview(kind: str, filename: str):
    # kind: 'overlay_input' | 'backgrounds' | 'output'
    base = {
        "overlay_input": OV_DIR,
        "backgrounds": BG_DIR,
        "output": OUT_DIR,
    }.get(kind)
    if not base:
        abort(404)
    path = base / filename
    if not path.exists():
        abort(404)
    # 単純にファイル配信
    rel = f"{base.relative_to(BASE_DIR)}/{filename}"
    return f"""
    <h2>Preview: {kind}/{filename}</h2>
    { '<video controls style="max-width:90vw" src="/' + rel + '"></video>' if is_video_name(filename) else '<img style="max-width:90vw" src="/' + rel + '"/>' }
    <p><a href="/">戻る</a></p>
    """

@app.route("/download/output/<filename>")
def download_output(filename: str):
    path = OUT_DIR / filename
    if not path.exists():
        abort(404)
    return send_from_directory(OUT_DIR, filename, as_attachment=True)

# ---------- アップロード ----------
@app.route("/upload", methods=["POST"])
def upload():
    target = request.args.get("target", "overlay")
    f = request.files.get("file")
    if not f or not f.filename:
        return redirect(url_for("index"))

    if target == "backgrounds":
        dest_dir = BG_DIR
    else:
        dest_dir = OV_DIR

    dest = dest_dir / Path(f.filename).name
    dest_dir.mkdir(parents=True, exist_ok=True)
    f.save(dest)

    # サムネ生成（非致命）
    try:
        ensure_thumb(dest)
    except Exception:
        pass

    return redirect(url_for("index"))

# ---------- 素材：順序/テキストの保存 ----------
@app.route("/materials/sync", methods=["POST"])
def materials_sync():
    js = request.get_json(silent=True) or {}
    order = js.get("order", [])
    texts = js.get("texts", {})

    if isinstance(order, list):
        save_order(order)
    if isinstance(texts, dict):
        # 既存とマージ（空文字は空で保持）
        cur = load_overrides()
        cur.update(texts)
        save_overrides(cur)
    return jsonify({"ok": True})

@app.route("/materials/delete", methods=["POST"])
def materials_delete():
    filename = request.form.get("filename", "")
    if not filename:
        return redirect(url_for("index"))
    p = OV_DIR / Path(filename).name
    if p.exists():
        try:
            p.unlink()
        except Exception:
            pass
    # サムネも削除
    th = TH_DIR / (Path(filename).name + ".jpg")
    if th.exists():
        try:
            th.unlink()
        except Exception:
            pass
    return redirect(url_for("index"))

# ---------- 合成 ----------
@app.route("/combine", methods=["POST"])
def combine():
    background = request.form.get("background", "").strip()
    overlay = request.form.get("overlay", "").strip()
    pos = request.form.get("pos", "top-right")
    size_pct = float(request.form.get("size_pct", "50") or 50)
    duration_mode = request.form.get("duration_mode", "shortest")  # shortest | background
    fadein = float(request.form.get("fadein", "0") or 0)

    text_enable = request.form.get("text_enable") == "on"
    text_mode = request.form.get("text_mode", "custom")  # custom | random
    text_input = request.form.get("text_input", "").strip()
    text_pos = request.form.get("text_pos", "top-left")
    text_size = int(float(request.form.get("text_size", "64") or 64))

    if not background or not overlay:
        return redirect(url_for("index"))

    bg_path = BG_DIR / background
    ov_path = OV_DIR / overlay
    if not (bg_path.exists() and ov_path.exists()):
        return redirect(url_for("index"))

    # テキスト決定
    overrides = load_overrides()
    material_text = overrides.get(overlay, "")
    if text_input:
        text_content = text_input
    elif text_mode == "random":
        text_content = random_line()
    else:
        text_content = material_text

    # 出力ファイル名
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_name = f"{Path(background).stem}__{Path(overlay).stem}__{stamp}.mp4"
    out_path = OUT_DIR / out_name

    # 合成
    try:
        with VideoFileClip(str(bg_path)) as bg:
            clips = [bg]
            # overlay
            if is_video_name(overlay):
                with VideoFileClip(str(ov_path)) as ov:
                    # リサイズ
                    scale = max(10.0, min(200.0, size_pct)) / 100.0
                    new_h = int(bg.h * scale)
                    ov_resized = ov.resize(height=new_h)
                    # 位置
                    x, y = map_pos(pos, bg.w, bg.h, ov_resized.w, ov_resized.h)
                    ov_resized = ov_resized.set_position((x, y))
                    if fadein > 0:
                        ov_resized = ov_resized.fx(vfx.fadein, fadein)
                    clips.append(ov_resized)

                    # テキスト
                    if text_enable and text_content:
                        img = text_to_image(text_content, font_size=text_size)
                        # 画像を MoviePy Clip に
                        bio = io.BytesIO()
                        img.save(bio, format="PNG")
                        bio.seek(0)
                        text_clip = ImageClip(bio).set_duration(ov.duration if duration_mode == "shortest" else bg.duration)
                        # テキストサイズに準じて位置
                        txt_w, txt_h = img.size
                        tx, ty = map_pos(text_pos, bg.w, bg.h, txt_w, txt_h)
                        text_clip = text_clip.set_position((tx, ty))
                        clips.append(text_clip)

                    # 書き出し
                    dur = min(bg.duration, ov.duration) if duration_mode == "shortest" else bg.duration
                    final = CompositeVideoClip(clips).set_duration(dur)
                    final.write_videofile(
                        str(out_path),
                        codec="libx264",
                        audio_codec="aac",
                        fps=bg.fps or 24,
                        threads=2,
                        preset="medium",
                        verbose=False,
                        logger=None,
                    )
            else:
                # overlay が画像
                img = Image.open(ov_path).convert("RGBA")
                # Pillow→ImageClip
                bio = io.BytesIO()
                img.save(bio, format="PNG")
                bio.seek(0)
                scale = max(10.0, min(200.0, size_pct)) / 100.0
                target_h = int(bg.h * scale)
                ov_clip = ImageClip(bio).set_duration(bg.duration).resize(height=target_h)
                x, y = map_pos(pos, bg.w, bg.h, ov_clip.w, ov_clip.h)
                ov_clip = ov_clip.set_position((x, y))
                if fadein > 0:
                    ov_clip = ov_clip.fx(vfx.fadein, fadein)
                clips.append(ov_clip)

                if text_enable and text_content:
                    timg = text_to_image(text_content, font_size=text_size)
                    tbio = io.BytesIO()
                    timg.save(tbio, format="PNG")
                    tbio.seek(0)
                    text_clip = ImageClip(tbio).set_duration(bg.duration)
                    txt_w, txt_h = timg.size
                    tx, ty = map_pos(text_pos, bg.w, bg.h, txt_w, txt_h)
                    text_clip = text_clip.set_position((tx, ty))
                    clips.append(text_clip)

                final = CompositeVideoClip(clips).set_duration(bg.duration)
                final.write_videofile(
                    str(out_path),
                    codec="libx264",
                    audio_codec="aac",
                    fps=bg.fps or 24,
                    threads=2,
                    preset="medium",
                    verbose=False,
                    logger=None,
                )

    except Exception as e:
        return f"Error in combine: {e}", 500

    # サムネ準備
    try:
        ensure_thumb(out_path)
    except Exception:
        pass

    return redirect(url_for("index"))

# ---------- アカウントAPI ----------
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

# ---------- IG投稿（※エンドポイント名は一意に） ----------
@app.route("/publish", methods=["POST"], endpoint="publish_reel")
def publish_reel_api():
    """
    JSON入力:
    {
      "account_no": "1",
      "filename": "output_xxx.mp4",  # static/output 内
      "caption": "任意"
    }
    """
    data = request.get_json(silent=True) or {}
    acc_no = str(data.get("account_no", "")).strip()
    filename = data.get("filename", "")
    caption = data.get("caption", "")

    if not acc_no or not filename:
        return {"ok": False, "error": "account_no and filename are required"}, 400

    # アカウント取得
    accs = _load_accounts()
    account = next((a for a in accs.get("accounts", []) if str(a.get("no", "")) == acc_no), None)
    if not account:
        return {"ok": False, "error": "account not found"}, 404

    ig_user_id = account.get("ig_user_id", "")
    access_token = account.get("access_token", "")
    if not ig_user_id or not access_token:
        return {"ok": False, "error": "ig_user_id/access_token missing"}, 400

    # ファイル存在
    local_path = OUT_DIR / Path(filename).name
    if not local_path.exists():
        return {"ok": False, "error": "file not found"}, 404

    # Cloudinaryへ
    try:
        url, rtype = upload_media_local(str(local_path))
    except Exception as e:
        return {"ok": False, "error": f"cloudinary upload failed: {e}"}, 500

    # Graph API 投稿
    try:
        result = ig_post_now(ig_user_id, url, True, caption, access_token)
    except Exception as e:
        return {"ok": False, "error": f"graph publish failed: {e}"}, 500

    return result

# ---------- 設定バックアップ（任意） ----------
@app.route("/settings/export", methods=["POST"])
def settings_export():
    try:
        res = cloud_backup()
        return {"ok": True, "result": res}
    except Exception as e:
        return {"ok": False, "error": str(e)}, 500

@app.route("/settings/import", methods=["POST"])
def settings_import():
    try:
        cloud_restore()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}, 500

# =======================================
# 起動
# =======================================
if __name__ == "__main__":
    # ローカルデバッグ用
    app.run(host="0.0.0.0", port=8000, debug=True)
