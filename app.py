# poster_core_reel.py  — Python 3.9 互換版
import os
import random
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, List, Dict

import numpy as np
from moviepy.editor import VideoFileClip, ImageClip, CompositeVideoClip
from PIL import Image, ImageDraw, ImageFont

# 依存の存在チェック（どこで落ちたか見えるように）
_missing: List[str] = []
try:
    import poster_core_reel_graph_accounts as igpub
except Exception as e:
    _missing.append(f"poster_core_reel_graph_accounts import error: {e}")

try:
    from cloudinary_uploader import upload_video_get_urls
except Exception as e:
    _missing.append(f"cloudinary_uploader import error: {e}")

SUPPORTED_EXTS = {
    "jpg", "jpeg", "png", "bmp", "gif", "webp",
    "mp4", "mov", "m4v", "avi", "mkv", "webm"
}

BASE_DIR: Path = Path(__file__).parent.resolve()
# Web 版の配置に合わせる（素材/出力は static 配下）
OVERLAY_DIR: Path = BASE_DIR / "static" / "overlay_input"
OUTPUT_DIR: Path = BASE_DIR / "static" / "output"
TEXT_FILE: Path = BASE_DIR / "random_texts.txt"
OVERRIDES_JSON: Path = BASE_DIR / "material_overrides.json"
FONT_PATH: Path = Path(os.environ.get("REEL_FONT_PATH", ""))  # 任意
LOG_DIR: Path = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True, parents=True)

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
    動画合成 → Cloudinary へアップロード → Graph API 投稿
    custom_overlay_text が None/空文字なら random_texts.txt からランダムに選ぶ
    """

    def __init__(self) -> None:
        if _missing:
            # 依存不足を早めに可視化
            raise ImportError("; ".join(_missing))

    def post_reel(
        self,
        account_no: int,
        overlay_path: Path,
        background_path: Path,
        custom_overlay_text: Optional[str] = None,
        share_to_feed: bool = False,
    ) -> str:
        """
        合成 → Cloudinary → IG 投稿。戻り値は media_id（文字列）
        """
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
            share_to_feed=share_to_feed,
        )

        # 6) 後片付け（出力一時ファイルの削除は任意）
        try:
            out_path.unlink(missing_ok=True)  # type: ignore[attr-defined]
        except Exception:
            pass

        return str(media_id)

    # ---------------- internal helpers ----------------

    def _decide_overlay_text(self, filename: str, custom_overlay_text: Optional[str]) -> str:
        if custom_overlay_text and custom_overlay_text.strip():
            return custom_overlay_text.strip()
        return self._get_random_text()

    def _build_caption(self) -> str:
        eng_tag = random.choice(ENGLISH_TAGS)
        return "☝🏻ストーリーみてねん🔞 #おもしろ動画 #裏垢 #裏垢女子 #フォロー " + eng_tag

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
        """
        背景: background_path
        素材: overlay_path（画像なら 6 秒固定）
        テキスト: overlay_text（None/空=無効）
        出力: output_path（mp4）
        """
        bg = VideoFileClip(str(background_path))

        ext = overlay_path.suffix.lower().lstrip(".")
        if ext in {"jpg", "jpeg", "png", "bmp", "webp"}:
            overlay_clip = ImageClip(str(overlay_path)).set_duration(6.0)
            duration = 6.0
        else:
            overlay_clip = VideoFileClip(str(overlay_path))
            duration = float(overlay_clip.duration or 0.0)
            # 背景の長さ調整
            if (bg.duration or 0.0) < duration:
                bg = bg.loop(duration=duration)
            else:
                bg = bg.set_duration(duration)

        # 素材を中央に収まる最大サイズにスケール（90%以内）
        scale = min((bg.w * 0.9) / overlay_clip.w, (bg.h * 0.9) / overlay_clip.h)
        overlay_resized = overlay_clip.resize(scale).set_position("center").crossfadein(2.0)

        clips = [bg.set_duration(duration), overlay_resized.set_duration(duration)]

        # テキスト（白地＋黒文字の丸角パネル）— 失敗しても動画出力は続行
        if overlay_text:
            try:
                fontsize = max(24, int(bg.h * 0.05))
                font = None
                try:
                    if FONT_PATH and FONT_PATH.exists():
                        font = ImageFont.truetype(str(FONT_PATH), fontsize)
                except Exception:
                    font = None
                if font is None:
                    font = ImageFont.load_default()

                # 文字サイズからパネル画像を作る
                try:
                    bbox = font.getbbox(overlay_text)  # Pillow 9+
                    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
                except Exception:
                    # Fallback
                    text_w, text_h = (fontsize * len(overlay_text), int(fontsize * 1.4))

                pad_x = int(text_w * 0.20)
                pad_y = int(text_h * 0.40)

                img = Image.new("RGBA", (text_w + pad_x, text_h + pad_y), (0, 0, 0, 0))
                draw = ImageDraw.Draw(img)
                # 白背景
                draw.rounded_rectangle(
                    (0, 0, img.width, img.height),
                    radius=20,
                    fill=(255, 255, 255, 255),
                )
                # 黒文字
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

        # 書き出し（libx264/aac）
        final.write_videofile(
            str(output_path),
            fps=bg.fps,
            codec="libx264",
            audio_codec="aac",
            preset="medium",
            threads=4
        )
