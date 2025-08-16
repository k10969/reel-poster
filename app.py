import os
import time
import json
from pathlib import Path
from typing import Tuple

from flask import (
    Flask, render_template, request, redirect, url_for,
    send_from_directory, abort
)
from werkzeug.utils import secure_filename

# MoviePy 1.0.3 想定
from moviepy.editor import VideoFileClip, CompositeVideoClip, ImageClip, vfx
from PIL import Image, ImageDraw, ImageFont
import numpy as np

BASE_DIR = Path(__file__).parent.resolve()
STATIC_DIR = BASE_DIR / "static"
BACKGROUND_DIR = STATIC_DIR / "backgrounds"
OVERLAY_DIR = STATIC_DIR / "overlay_input"
THUMB_DIR = STATIC_DIR / "thumbs"
OUTPUT_DIR = STATIC_DIR / "output"
RANDOM_TXT = BASE_DIR / "random_texts.txt"

MATERIALS_ORDER = BASE_DIR / "materials_order.json"
MATERIAL_OVERRIDES = BASE_DIR / "material_overrides.json"
ACCOUNTS_JSON = BASE_DIR / "accounts.json"

ALLOWED_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

for p in (BACKGROUND_DIR, OVERLAY_DIR, THUMB_DIR, OUTPUT_DIR):
    p.mkdir(parents=True, exist_ok=True)

if not RANDOM_TXT.exists():
    RANDOM_TXT.write_text("やばい\nおもしろすぎる\nこれすごい\n", encoding="utf-8")

DISABLE_THUMBS = os.getenv("DISABLE_THUMBS") == "1"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024  # 512MB

# -------- utils --------
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
        "center": ((bg_w - ov_w) // 2, (bg_h - ov_h) // 2),
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

def _load_json(p: Path, default):
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default

def _save_json(p: Path, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

# -------- routes --------
@app.route("/")
def index():
    bgs = list_files_sorted(BACKGROUND_DIR)
    ovs = list_files_sorted(OVERLAY_DIR)
    outs = list_files_sorted(OUTPUT_DIR)

    # 背景
    bg_rows = []
    for name in bgs:
        src = BACKGROUND_DIR / name
        th = THUMB_DIR / f"bg__{name}.jpg"
        try:
            if not DISABLE_THUMBS:
                ensure_thumbnail(src, th)
        except Exception:
            pass
        bg_rows.append((name, f"static/thumbs/{th.name}" if th.exists() else ""))

    # 並び順＆テキスト上書き
    order = _load_json(MATERIALS_ORDER, [])
    overrides = _load_json(MATERIAL_OVERRIDES, {})

    ov_set = set(ovs)
    ordered = [f for f in order if f in ov_set] + [f for f in ovs if f not in order]

    ov_rows = []
    for name in ordered:
        src = OVERLAY_DIR / name
        th = THUMB_DIR / f"ov__{name}.jpg"
        try:
            if not DISABLE_THUMBS:
                ensure_thumbnail(src, th)
        except Exception:
            pass
        text_override = overrides.get(name, {}).get("text", "")
        ov_rows.append({
            "name": name,
            "thumb": f"static/thumbs/{th.name}" if th.exists() else "",
            "text": text_override
        })

    return render_template("index.html", bg_rows=bg_rows, ov_rows=ov_rows, outs_rows=outs)

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
        prefix = "bg" if target == "backgrounds" else "ov"
        if not DISABLE_THUMBS:
            ensure_thumbnail(folder / fname, THUMB_DIR / f"{prefix}__{fname}.jpg")
    except Exception:
        pass

    # 新規素材は order の末尾へ
    if target != "backgrounds":
        order = _load_json(MATERIALS_ORDER, [])
        if fname not in order:
            order.append(fname)
            _save_json(MATERIALS_ORDER, order)

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

# 並び順・テキスト保存
@app.route("/materials/sync", methods=["POST"])
def materials_sync():
    data = request.get_json(silent=True) or {}
    order = data.get("order", [])
    texts = data.get("texts", {})

    current = {f.name for f in OVERLAY_DIR.iterdir() if f.is_file() and is_allowed(f.name)}
    cleaned_order = [f for f in order if f in current]
    cleaned_texts = {k: {"text": (v or "").strip()} for k, v in texts.items() if k in current}

    _save_json(MATERIALS_ORDER, cleaned_order)
    overrides = _load_json(MATERIAL_OVERRIDES, {})
    overrides.update(cleaned_texts)
    _save_json(MATERIAL_OVERRIDES, overrides)

    return {"ok": True, "count": len(cleaned_order)}

# 素材削除
@app.route("/materials/delete", methods=["POST"])
def materials_delete():
    filename = request.form.get("filename", "")
    path = safe_join(OVERLAY_DIR, filename)
    if not path.exists():
        abort(404)
    try:
        path.unlink(missing_ok=True)
        (THUMB_DIR / f"ov__{filename}.jpg").unlink(missing_ok=True)
    except Exception:
        pass

    order = _load_json(MATERIALS_ORDER, [])
    order = [f for f in order if f != filename]
    _save_json(MATERIALS_ORDER, order)

    overrides = _load_json(MATERIAL_OVERRIDES, {})
    overrides.pop(filename, None)
    _save_json(MATERIAL_OVERRIDES, overrides)

    return redirect(url_for("index"))

@app.route("/combine", methods=["POST"])
def combine():
    bg = request.form.get("background")
    ov = request.form.get("overlay")
    pos = request.form.get("pos", "top-right")
    size_pct = float(request.form.get("size_pct", "50"))
    duration_mode = request.form.get("duration_mode", "shortest")
    fadein = float(request.form.get("fadein", "0"))

    text_enable = request.get_json(silent=True) is None and (request.form.get("text_enable") == "on")
    text_mode = request.form.get("text_mode", "custom")
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
                    "center": ((bg_w - overlay_w)//2, (bg_h - overlay_h)//2),
                }
                return mapping.get(pos, mapping["top-right"])

            overrides = _load_json(MATERIAL_OVERRIDES, {})
            override_text = overrides.get(ov_path.name, {}).get("text", "").strip()
            candidate = (text_input or "").strip() or override_text

            if ov_path.suffix.lower() in VIDEO_EXTS:
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
                        if text_mode == "custom" and candidate:
                            line = candidate
                        else:
                            lines = [s.strip() for s in RANDOM_TXT.read_text(encoding="utf-8").splitlines() if s.strip()]
                            line = lines[int(time.time()) % len(lines)] if lines else ""
                        if line:
                            img = render_text_image(line, font_size=text_size)
                            txt_clip = ImageClip(np.array(img)).set_duration(final_dur)
                            tx, ty = calc_position(text_pos, bg_w, bg_h, txt_clip.w, txt_clip.h)
                            txt_clip = txt_clip.set_position((tx, ty))
                            clips.append(txt_clip)

                    final = CompositeVideoClip(clips)
                    final.write_videofile(
                        str(out_path),
                        codec="libx264", audio_codec="aac",
                        threads=2,
                        fps=bg_clip.fps if bg_clip.fps else 30,
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
                    if text_mode == "custom" and candidate:
                        line = candidate
                    else:
                        lines = [s.strip() for s in RANDOM_TXT.read_text(encoding="utf-8").splitlines() if s.strip()]
                        line = lines[int(time.time()) % len(lines)] if lines else ""
                    if line:
                        img = render_text_image(line, font_size=text_size)
                        txt_clip = ImageClip(np.array(img)).set_duration(final_dur)
                        tx, ty = calc_position(text_pos, bg_w, bg_h, txt_clip.w, txt_clip.h)
                        txt_clip = txt_clip.set_position((tx, ty))
                        clips.append(txt_clip)

                final = CompositeVideoClip(clips)
                final.write_videofile(
                    str(out_path),
                    codec="libx264", audio_codec="aac",
                    threads=2,
                    fps=bg_clip.fps if bg_clip.fps else 30,
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

# ---- Accounts (UI保存のみ) ----
def _load_accounts():
    if ACCOUNTS_JSON.exists():
        try:
            return json.loads(ACCOUNTS_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"accounts": []}

def _save_accounts(obj):
    ACCOUNTS_JSON.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

@app.route("/accounts", methods=["GET"])
def accounts_list():
    return _load_accounts()

@app.route("/accounts/upsert", methods=["POST"])
def accounts_upsert():
    data = request.get_json(silent=True) or {}
    no = str(data.get("no", "")).strip()
    if not no:
        return {"ok": False, "error": "no required"}, 400
    accs = _load_accounts()
    found = False
    for a in accs["accounts"]:
        if str(a.get("no", "")) == no:
            a.update({
                "no": no,
                "label": data.get("label", ""),
                "ig_user_id": data.get("ig_user_id", ""),
                "page_id": data.get("page_id", "")
            })
            found = True
            break
    if not found:
        accs["accounts"].append({
            "no": no,
            "label": data.get("label", ""),
            "ig_user_id": data.get("ig_user_id", ""),
            "page_id": data.get("page_id", "")
        })
    _save_accounts(accs)
    return {"ok": True}

@app.route("/accounts/delete", methods=["POST"])
def accounts_delete():
    data = request.get_json(silent=True) or {}
    no = str(data.get("no", "")).strip()
    if not no:
        return {"ok": False, "error": "no required"}, 400
    accs = _load_accounts()
    accs["accounts"] = [a for a in accs["accounts"] if str(a.get("no", "")) != no]
    _save_accounts(accs)
    return {"ok": True}

@app.route("/random_texts", methods=["GET", "POST"])
def random_texts():
    if request.method == "POST":
        txt = request.form.get("content", "")
        RANDOM_TXT.write_text(txt, encoding="utf-8")
        return redirect(url_for("random_texts"))
    content = RANDOM_TXT.read_text(encoding="utf-8") if RANDOM_TXT.exists() else ""
    return render_template("random_texts.html", content=content)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

