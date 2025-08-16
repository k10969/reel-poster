import os
import random
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import numpy as np
from moviepy.editor import VideoFileClip, ImageClip, CompositeVideoClip
from PIL import Image, ImageDraw, ImageFont

import poster_core_reel_graph_accounts as igpub
from cloudinary_uploader import upload_video_get_urls

SUPPORTED_EXTS = {"jpg", "jpeg", "png", "bmp", "gif", "webp", "mp4", "mov", "m4v", "avi", "mkv", "webm"}

BASE_DIR = Path(__file__).parent.resolve()
OVERLAY_DIR = BASE_DIR / "overlay_input"
OUTPUT_DIR = BASE_DIR / "output"
TEXT_FILE = BASE_DIR / "random_texts.txt"
OVERRIDES_JSON = BASE_DIR / "material_overrides.json"
FONT_PATH = Path(os.environ.get("REEL_FONT_PATH", ""))
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

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

class PosterCoreReel:
    """
    動画合成 → Cloudinary → Graph API 投稿
    “custom_overlay_text” が空なら random_texts.txt から選ぶ
    """

    def post_reel(
        self,
        account_no: int,
        overlay_path: Path,
        background_path: Path,
        custom_overlay_text: str | None = None,
        share_to_feed: bool = False,
    ) -> str:
        overlay_path = Path(overlay_path)
        background_path = Path(background_path)

        # 1) 動画に焼くテキストを決定
        overlay_text = self._decide_overlay_text(overlay_path.name, custom_overlay_text)

        # 2) 動画生成
        out_path = OUTPUT_DIR / f"{overlay_path.stem}_out.mp4"
        self._create_video(background_path, overlay_path, out_path, overlay_text)

        # 3) Cloudinary へアップロード
        LOG.info("Uploading to Cloudinary...")
        video_url, cover_url, public_id = upload_video_get_urls(str(out_path), thumbnail_sec=1.0)
        LOG.info("Cloudinary uploaded: public_id=%s", public_id)
        LOG.info("Cloudinary URL: %s", video_url)

        # 4) 投稿用キャプション
        caption = self._build_caption()

        # 5) Graph API に投稿（アップロード済みのURLを渡す）
        media_id = igpub.post_reel(
            video_url=video_url,
            cover_url=cover_url,
            caption=caption,
            account_no=account_no,
            force_refresh=False,
            log_file=str(LOG_DIR / "ig_poster.log"),
        )

        # 6) 後片付け
        try:
            out_path.unlink(missing_ok=True)
        except Exception:
            pass
        return media_id

    def _decide_overlay_text(self, filename: str, custom_overlay_text: str | None) -> str:
        if custom_overlay_text and custom_overlay_text.strip():
            return custom_overlay_text.strip()
        return self._get_random_text()

    def _build_caption(self) -> str:
        eng_tag = random.choice(ENGLISH_TAGS)
        return f"☝🏻ストーリーみてねん🔞 #おもしろ動画 #裏垢 #裏垢女子 #フォロー {eng_tag}"

    def _get_random_text(self) -> str:
        if not TEXT_FILE.exists():
            return ""
        try:
            lines = [ln.strip() for ln in TEXT_FILE.read_text(encoding="utf-8").splitlines() if ln.strip()]
            return random.choice(lines) if lines else ""
        except Exception:
            return ""

    def _create_video(self, background_path: Path, overlay_path: Path, output_path: Path, overlay_text: str | None):
        bg = VideoFileClip(str(background_path))

        ext = overlay_path.suffix.lower().lstrip(".")
        if ext in {"jpg", "jpeg", "png", "bmp", "webp"}:
            overlay_clip = ImageClip(str(overlay_path)).set_duration(6.0)
            duration = 6.0
        else:
            overlay_clip = VideoFileClip(str(overlay_path))
            duration = overlay_clip.duration
            if bg.duration < duration:
                bg = bg.loop(duration=duration)
            else:
                bg = bg.set_duration(duration)

        scale = min((bg.w * 0.9) / overlay_clip.w, (bg.h * 0.9) / overlay_clip.h)
        overlay_resized = overlay_clip.resize(scale).set_position("center").crossfadein(2.0)

        clips = [bg.set_duration(duration), overlay_resized.set_duration(duration)]

        if overlay_text:
            try:
                fontsize = int(bg.h * 0.05)
                font = None
                try:
                    if FONT_PATH and FONT_PATH.exists():
                        font = ImageFont.truetype(str(FONT_PATH), fontsize)
                except Exception:
                    font = None
                if font is None:
                    font = ImageFont.load_default()

                bbox = font.getbbox(overlay_text)
                text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
                pad_x = int(text_w * 0.2)
                pad_y = int(text_h * 0.4)

                img = Image.new("RGBA", (text_w + pad_x, text_h + pad_y), (0, 0, 0, 0))
                draw = ImageDraw.Draw(img)
                draw.rounded_rectangle((0, 0, img.width, img.height), radius=20, fill=(255, 255, 255, 255))
                draw.text(((img.width - text_w) // 2, (img.height - text_h) // 2),
                          overlay_text, font=font, fill=(0, 0, 0, 255))

                txt_clip = ImageClip(np.array(img)).set_duration(duration)
                txt_clip = txt_clip.set_position(("center", int(bg.h * 0.1)))
                clips.append(txt_clip)
            except Exception as e:
                LOG.warning("テキスト合成エラー: %s", e)

        final = CompositeVideoClip(clips)
        final.write_videofile(str(output_path), fps=bg.fps, codec="libx264", audio_codec="aac", preset="medium", threads=4)
