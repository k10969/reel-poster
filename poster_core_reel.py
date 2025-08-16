# poster_core_reel.py — Unicode-safe JP text / MoviePy progress hidden / Py3.9 OK
from __future__ import annotations

import os
import random
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

import numpy as np
from moviepy.editor import VideoFileClip, ImageClip, CompositeVideoClip
from PIL import Image, ImageDraw, ImageFont

import poster_core_reel_graph_accounts as igpub
from cloudinary_uploader import upload_video_get_urls

SUPPORTED_EXTS = {
    "jpg", "jpeg", "png", "bmp", "gif", "webp",
    "mp4", "mov", "m4v", "avi", "mkv", "webm"
}

BASE_DIR = Path(__file__).parent.resolve()
OVERLAY_DIR = BASE_DIR / "static" / "overlay_input"
OUTPUT_DIR = BASE_DIR / "static" / "output"
TEXT_FILE = BASE_DIR / "random_texts.txt"
FONT_PATH = Path(os.environ.get("REEL_FONT_PATH", ""))  # 任意（未設定OK）
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

LOG = logging.getLogger("poster_core_reel")
if not LOG.handlers:
    LOG.setLevel(logging.INFO)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s"))
    LOG.addHandler(ch)
    fh = RotatingFileHandler(LOG_DIR / "core.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    LOG.addHandler(fh)

ENGLISH_TAGS = ["#fun", "#cool", "#amazing", "#wow", "#viral", "#loveit"]

def _pick_font(font_size: int) -> ImageFont.FreeTypeFont:
    """
    日本語を確実に描画できるフォントを探す。
    優先: REEL_FONT_PATH -> project/fonts -> static/fonts -> Noto/DejaVu -> 最後にデフォルト
    """
    candidates = []

    # 1) 明示（環境変数）
    if FONT_PATH and FONT_PATH.exists():
        candidates.append(FONT_PATH)

    # 2) リポジトリ直下の fonts/（あなたが置いた場所）
    candidates += [
        BASE_DIR / "fonts" / "keiofont.ttf",   # ← これを最優先で見る
        BASE_DIR / "fonts" / "keifont.ttf",    # 表記ゆれ対策
        BASE_DIR / "fonts" / "NotoSansJP-Regular.otf",
        BASE_DIR / "fonts" / "NotoSansCJK-Regular.ttc",
    ]

    # 3) static/fonts/（もしここに置いた場合）
    candidates += [
        BASE_DIR / "static" / "fonts" / "keiofont.ttf",
        BASE_DIR / "static" / "fonts" / "keifont.ttf",
        BASE_DIR / "static" / "fonts" / "NotoSansJP-Regular.otf",
        BASE_DIR / "static" / "fonts" / "NotoSansCJK-Regular.ttc",
    ]

    # 4) システム（Dockerで noto/dejavu を入れる場合）
    candidates += [
        Path("/usr/share/fonts/truetype/noto/NotoSansJP-Regular.otf"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]

    for p in candidates:
        try:
            if p and p.exists():
                return ImageFont.truetype(str(p), font_size)
        except Exception:
            continue

    LOG.warning("フォント未検出: load_default() にフォールバック（日本語は豆腐の可能性）")
    return ImageFont.load_default()

class PosterCoreReel:
    """
    動画合成 → Cloudinary → Graph API 投稿
    - custom_overlay_text が空なら random_texts.txt から選ぶ
    - 画像素材は6秒動画化
    - 背景は尺を合わせ、足りなければループ
    - MoviePy の進捗は logger=None で非表示
    """

    def post_reel(
        self,
        account_no: int,
        overlay_path: Path,
        background_path: Path,
        custom_overlay_text: Optional[str] = None,
        share_to_feed: bool = False,
    ) -> str:
        overlay_path = Path(overlay_path)
        background_path = Path(background_path)

        overlay_text = self._decide_overlay_text(overlay_path.name, custom_overlay_text)

        out_path = OUTPUT_DIR / f"{overlay_path.stem}_out.mp4"
        self._create_video(background_path, overlay_path, out_path, overlay_text)

        LOG.info("Uploading to Cloudinary...")
        video_url, cover_url, public_id = upload_video_get_urls(str(out_path), thumbnail_sec=1.0)
        LOG.info("Cloudinary uploaded: public_id=%s", public_id)
        LOG.info("Cloudinary URL: %s", video_url)

        caption = self._build_caption()
        media_id = igpub.post_reel(
            video_url=video_url,
            cover_url=cover_url,
            caption=caption,
            account_no=account_no,
            force_refresh=False,
            log_file=str(LOG_DIR / "ig_publisher.log"),
            share_to_feed=share_to_feed,
        )

        try:
            out_path.unlink(missing_ok=True)
        except Exception:
            pass

        return str(media_id)

    # ===== 内部 =====

    def _decide_overlay_text(self, filename: str, custom_overlay_text: Optional[str]) -> str:
        if custom_overlay_text and custom_overlay_text.strip():
            return str(custom_overlay_text).strip()
        return self._get_random_text()

    def _build_caption(self) -> str:
        eng_tag = random.choice(ENGLISH_TAGS)
        return f"☝🏻ストーリーみてねん🔞 #おもしろ動画 #裏垢 #裏垢女子 #フォロー {eng_tag}"

    def _get_random_text(self) -> str:
        if not TEXT_FILE.exists():
            return ""
        try:
            lines = [
                ln.strip()
                for ln in TEXT_FILE.read_text(encoding="utf-8").splitlines()
                if ln.strip()
            ]
            return random.choice(lines) if lines else ""
        except Exception:
            return ""

    def _create_video(
        self,
        background_path: Path,
        overlay_path: Path,
        output_path: Path,
        overlay_text: Optional[str],
    ) -> None:
        bg = VideoFileClip(str(background_path))

        ext = overlay_path.suffix.lower().lstrip(".")
        if ext in {"jpg", "jpeg", "png", "bmp", "gif", "webp"}:
            overlay_clip = ImageClip(str(overlay_path)).set_duration(6.0)  # 画像は6秒
            duration = 6.0
        else:
            overlay_clip = VideoFileClip(str(overlay_path))
            duration = overlay_clip.duration

        try:
            if bg.duration < duration:
                bg = bg.loop(duration=duration)
            else:
                bg = bg.set_duration(duration)
        except Exception:
            bg = bg.set_duration(duration)

        scale = min((bg.w * 0.9) / overlay_clip.w, (bg.h * 0.9) / overlay_clip.h)
        overlay_resized = overlay_clip.resize(scale).set_position("center")

        clips = [bg.set_duration(duration), overlay_resized.set_duration(duration)]

        if overlay_text:
            try:
                fontsize = max(24, int(bg.h * 0.05))
                font = _pick_font(fontsize)

                # Pillow>=10: getbbox
                bbox = font.getbbox(overlay_text)
                text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
                pad_x = int(max(20, text_w * 0.2))
                pad_y = int(max(16, text_h * 0.4))

                img = Image.new("RGBA", (text_w + pad_x, text_h + pad_y), (0, 0, 0, 0))
                draw = ImageDraw.Draw(img)
                draw.rounded_rectangle(
                    (0, 0, img.width, img.height),
                    radius=20,
                    fill=(255, 255, 255, 255),
                )
                draw.text(
                    ((img.width - text_w) // 2, (img.height - text_h) // 2),
                    overlay_text,
                    font=font,
                    fill=(0, 0, 0, 255),
                )

                txt_clip = ImageClip(np.array(img)).set_duration(duration)
                txt_clip = txt_clip.set_position(("center", int(bg.h * 0.1)))
                clips.append(txt_clip)
            except Exception as e:
                LOG.warning("テキスト合成エラー: %s", e)

        final = CompositeVideoClip(clips)
        try:
            final.write_videofile(
                str(output_path),
                fps=getattr(bg, "fps", 30) or 30,
                codec="libx264",
                audio_codec="aac",
                preset="medium",
                threads=2,
                logger=None  # ← tqdm等の進捗を完全非表示
            )
        finally:
            try:
                overlay_clip.close()
            except Exception:
                pass
            try:
                final.close()
            except Exception:
                pass
            try:
                bg.close()
            except Exception:
                pass
