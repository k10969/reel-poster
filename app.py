import os
import time
from pathlib import Path
from typing import Tuple

from flask import (
    Flask, render_template, request, redirect, url_for,
    send_from_directory, abort
)
from werkzeug.utils import secure_filename

from moviepy.editor import VideoFileClip, CompositeVideoClip, ImageClip, vfx
from PIL import Image, ImageDraw, ImageFont

# ========= 基本設定 =========
BASE_DIR = Path(__file__).parent.resolve()
STATIC_DIR = BASE_DIR / "static"
BACKGROUND_DIR = STATIC_DIR / "backgrounds"
OVERLAY_DIR = STATIC_DIR / "overlay_input"
THUMB_DIR = STATIC_DIR / "thumbs"
OUTPUT_DIR = STATIC_DIR / "output"
RANDOM_TXT = BASE_DIR / "random_texts.txt"

ALLOWED_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

for p in (BACKGROUND_DIR, OVERLAY_DIR, THUMB_DIR, OUTPUT_DIR):
    p.mkdir(parents=True, exist_ok=True)

# 初回 random_texts.txt がなければ作成
if not RANDOM_TXT.exists():
    RANDOM_TXT.write_text("やばい\nおもしろすぎる\nこれすごい\n", encoding="utf-8")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024  # 512MB

# ========= ユーティリティ =========
def is_allowed(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTS

def is_video(filename: str) -> bool:
    return Path(filename).suffix.lower() in VIDEO_EXTS

def list_files_sorted(folder: Path):
    files = [f.name for f in folder.iterdir() if f.is_file() and is_allowed(f.name)]
    files.sort(key=lambda n: (folder / n).stat().st_mtime, reverse=True)
    return files

def ensure_thumbnail(src_path: Path, thumb_path: Path, width: int = 320) -> None:
    if thumb_path.exists():
        return
    if is_video(src_path.name):
        with VideoFileClip(str(src_path)) as clip:
            t = min(1.0, max(0.0, clip.duration / 3.0))
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            clip.save_frame(str(thumb_path), t=t)
    else:
        img = Image.open(src_path).convert("RGB")
        w, h = img.size
        if w > width:
            r = width / w
            img = img.resize((int(w * r), int(h * r)))
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(thumb_path, "JPEG", quality=85)

def safe_join(folder: Path, filename: str) -> Path:
    name = secure_filename(filename)
    p = folder / name
    if not p.resolve().is_relative_to(folder.resolve()):
        abort(400)
    return p

def calc_position(pos_key: str, bg_w: int, bg_h: int, ov_w: int, ov_h: int) -> Tuple[int, int]:
    m = 12
    mapping = {
        "top-left": (m, m),
        "top-right": (bg_w - ov_w - m, m),
        "bottom-left": (m, bg_h - ov_h - m),
        "bottom-right": (bg_w - ov_w - m, bg_h - ov_h - m),
        "center": ((bg_w - ov_w)//2, (bg_h - ov_h)//2)
    }
    return mapping.get(pos_key, mapping["top-right"])

def render_text_image(text: str, font_size: int = 64, color: str = "#ffffff",
                      stroke_width: int = 4, stroke_color: str = "#000000",
                      padding: int = 16) -> Image.Image:
    try:
        custom_font = BASE_DIR / "static" / "fonts" / "keifont.ttf"
        if custom_font.exists():
            font = ImageFont.truetype(str(custom_font), font_size)
        else:
            font = ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    dummy = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    d0 = ImageDraw.Draw(dummy)
    bbox = d0.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]

    img = Image.new("RGBA", (w + padding * 2, h + padding * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.text((padding, padding), text, font=font, fill=color,
              stroke_width=stroke_width, stroke_fill=stroke_color)
    return img

# ========= ルーティング =========
@app.route("/")
def index():
    bgs = list_files_sorted(BACKGROUND_DIR)
    ovs = list_files_sorted(OVERLAY_DIR)
    outs = list_files_sorted(OUTPUT_DIR)

    bg_rows = []
    for name in bgs:
        src = BACKGROUND_DIR / name
        th = THUMB_DIR / f"bg__{name}.jpg"
        try:
            ensure_thumbnail(src, th)
        except Exception:
            pass
        bg_rows.append((name, f"static/thumbs/{th.name}" if th.exists() else ""))

    ov_rows = []
    for name in ovs:
        src = OVERLAY_DIR / name
        th = THUMB_DIR / f"ov__{name}.jpg"
        try:
            ensure_thumbnail(src, th)
        except Exception:
            pass
        ov_rows.append((name, f"static/thumbs/{th.name}" if th.exists() else ""))

    outs_rows = outs
    return render_template("index.html", bg_rows=bg_rows, ov_rows=ov_rows, outs_rows=outs_rows)

@app.route("/upload", methods=["POST"])
def upload():
    target = request.args.get("target", "overlay")  # backgrounds | overlay
    file = request.files.get("file")
    if not file or not file.filename:
        return redirect(url_for("index"))
    if not is_allowed(file.filename):
        return "Unsupported file type", 400

    fname = secure_filename(file.filename)
    folder = BACKGROUND_DIR if target == "backgrounds" else OVERLAY_DIR
    file.save(folder / fname)
    try:
        ensure_thumbnail(folder / fname, THUMB_DIR / f"{'bg' if target=='backgrounds' else 'ov'}__{fname}.jpg")
    except Exception:
        pass
    return redirect(url_for("index"))

@app.route("/preview/<kind>/<filename>")
def preview(kind: str, filename: str):
    if kind not in {"backgrounds", "overlay_input", "output"}:
        abort(404)
    folder = {"backgrounds": BACKGROUND_DIR, "overlay_input": OVERLAY_DIR, "output": OUTPUT_DIR}[kind]
    path = safe_join(folder, filename)
    if not path.exists():
        abort(404)
    return render_template("preview.html",
                           kind=kind,
                           filename=filename,
                           file_url=f"static/{kind}/{filename}",
                           is_video=is_video(filename))

@app.route("/combine", methods=["POST"])
def combine():
    bg = request.form.get("background")
    ov = request.form.get("overlay")
    pos = request.form.get("pos", "top-right")
    size_pct = float(request.form.get("size_pct", "50"))
    duration_mode = request.form.get("duration_mode", "shortest")  # shortest|background
    fadein = float(request.form.get("fadein", "0"))  # seconds

    text_enable = request.form.get("text_enable") == "on"
    text_mode = request.form.get("text_mode", "random")  # random|custom
    text_input = request.form.get("text_input", "")
    text_size = int(request.form.get("text_size", "64"))
    text_pos = request.form.get("text_pos", "top-left")

    if not bg or not ov:
        return "background and overlay are required", 400

    bg_path = safe_join(BACKGROUND_DIR, bg)
    ov_path = safe_join(OVERLAY_DIR, ov)
    if not bg_path.exists() or not ov_path.exists():
        abort(404)

    ts = int(time.time())
    out_name = f"{Path(bg).stem}__{Path(ov).stem}__{ts}.mp4"
    out_path = OUTPUT_DIR / out_name

    try:
        with VideoFileClip(str(bg_path)) as bg_clip:
            bg_w, bg_h = bg_clip.w, bg_clip.h
            base_len = min(bg_w, bg_h)
            overlay_target = max(1, int(base_len * (size_pct / 100.0)))

            def pos_xy(overlay_w, overlay_h):
                m = 12
                mapping = {
                    "top-left": (m, m),
                    "top-right": (bg_w - overlay_w - m, m),
                    "bottom-left": (m, bg_h - overlay_h - m),
                    "bottom-right": (bg_w - overlay_w - m, bg_h - overlay_h - m),
                    "center": ((bg_w - overlay_w)//2, (bg_h - overlay_h)//2)
                }
                return mapping.get(pos, mapping["top-right"])

            if Path(ov_path).suffix.lower() in VIDEO_EXTS:
                with VideoFileClip(str(ov_path)) as ov_clip:
                    overlay = ov_clip.resize(height=overlay_target) if ov_clip.w <= ov_clip.h else ov_clip.resize(width=overlay_target)
                    if fadein > 0:
                        overlay = overlay.fx(vfx.fadein, fadein)
                    ox, oy = pos_xy(overlay.w, overlay.h)
                    overlay = overlay.set_position((ox, oy))

                    if duration_mode == "background":
                        final_dur = bg_clip.duration
                    else:
                        final_dur = min(bg_clip.duration, overlay.duration)

                    clips = [bg_clip.set_duration(final_dur), overlay.set_duration(final_dur)]

                    if text_enable:
                        if text_mode == "custom" and text_input.strip():
                            line = text_input.strip()
                        else:
                            lines = [s.strip() for s in RANDOM_TXT.read_text(encoding="utf-8").splitlines() if s.strip()]
                            line = lines[int(time.time()) % len(lines)] if lines else ""
                        if line:
                            img = render_text_image(line, font_size=text_size)
                            txt_clip = ImageClip(img).set_duration(final_dur)
                            tx, ty = pos_xy(txt_clip.w, txt_clip.h) if text_pos == "same" else calc_position(text_pos, bg_w, bg_h, txt_clip.w, txt_clip.h)
                            txt_clip = txt_clip.set_position((tx, ty))
                            clips.append(txt_clip)

                    final = CompositeVideoClip(clips)
                    final.write_videofile(
                        str(out_path), codec="libx264", audio_codec="aac",
                        threads=4, fps=bg_clip.fps if bg_clip.fps else 30,
                        preset="medium"
                    )
                    final.close()
            else:
                img_clip = ImageClip(str(ov_path))
                overlay = img_clip.resize(height=overlay_target) if img_clip.w <= img_clip.h else img_clip.resize(width=overlay_target)
                if fadein > 0:
                    overlay = overlay.fx(vfx.fadein, fadein)
                ox, oy = pos_xy(overlay.w, overlay.h)

                if duration_mode == "background":
                    final_dur = bg_clip.duration
                else:
                    final_dur = min(bg_clip.duration, 15.0)

                overlay = overlay.set_duration(final_dur).set_position((ox, oy))
                clips = [bg_clip.set_duration(final_dur), overlay]

                if text_enable:
                    if text_mode == "custom" and text_input.strip():
                        line = text_input.strip()
                    else:
                        lines = [s.strip() for s in RANDOM_TXT.read_text(encoding="utf-8").splitlines() if s.strip()]
                        line = lines[int(time.time()) % len(lines)] if lines else ""
                    if line:
                        img = render_text_image(line, font_size=text_size)
                        txt_clip = ImageClip(img).set_duration(final_dur)
                        tx, ty = calc_position(text_pos, bg_w, bg_h, txt_clip.w, txt_clip.h)
                        txt_clip = txt_clip.set_position((tx, ty))
                        clips.append(txt_clip)

                final = CompositeVideoClip(clips)
                final.write_videofile(
                    str(out_path), codec="libx264", audio_codec="aac",
                    threads=4, fps=bg_clip.fps if bg_clip.fps else 30,
                    preset="medium"
                )
                final.close()

    except Exception as e:
        return f"Error during combine: {e}", 500

    return redirect(url_for("preview", kind="output", filename=out_name))

@app.route("/download/output/<filename>")
def download_output(filename: str):
    path = safe_join(OUTPUT_DIR, filename)
    if not path.exists():
        abort(404)
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)

@app.route("/static/<path:subpath>")
def static_passthrough(subpath: str):
    full = STATIC_DIR / subpath
    if not full.exists():
        abort(404)
    return send_from_directory(STATIC_DIR, subpath)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
