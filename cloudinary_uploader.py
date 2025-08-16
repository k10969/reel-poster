# cloudinary_uploader.py
import logging
logger = logging.getLogger(__name__)
from pathlib import Path
from typing import Optional, Tuple
from dotenv import load_dotenv
import os
import cloudinary
import cloudinary.uploader
from cloudinary.utils import cloudinary_url

BASE_DIR = Path(__file__).parent.resolve()
# プロジェクト直下の .env を必ず読む（CWDに依存しない）
load_dotenv(dotenv_path=BASE_DIR / ".env", override=False)

def _init_cloudinary():
    """
    Cloudinary設定を .env から初期化。
    - CLOUDINARY_URL があればそれを優先
    - なければ CLOUDINARY_CLOUD_NAME / CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET
    """
    url = os.getenv("CLOUDINARY_URL", "").strip()
    if url:
        cloudinary.config(secure=True)  # URLから自動設定 + https
    else:
        cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
        api_key = os.getenv("CLOUDINARY_API_KEY", "").strip()
        api_secret = os.getenv("CLOUDINARY_API_SECRET", "").strip()
        if not (cloud_name and api_key and api_secret):
            raise RuntimeError(
                "Cloudinary認証情報が見つかりません。\n"
                "- CLOUDINARY_URL=cloudinary://<API_KEY>:<API_SECRET>@<CLOUD_NAME>\n"
                "  または\n"
                "- CLOUDINARY_CLOUD_NAME / CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET を .env に設定してください。\n"
                f"読み込んだ .env: {BASE_DIR/'.env'}"
            )
        cloudinary.config(
            cloud_name=cloud_name,
            api_key=api_key,
            api_secret=api_secret,
            secure=True,
        )
    # 確認
    cfg = cloudinary.config()
    if not (cfg.api_key and cfg.api_secret and cfg.cloud_name):
        raise RuntimeError("Cloudinary設定が不完全です（api_key/secret/cloud_name）。.envを確認してください。")

def upload_video_get_urls(
    file_path: str,
    public_id: Optional[str] = None,
    folder: Optional[str] = "ig_reels",
    thumbnail_sec: float = 1.0
) -> Tuple[str, Optional[str], str]:
    """
    動画を Cloudinary にアップロードし、
    - video_url（公開 https 直リンク）
    - cover_url（指定秒のフレーム jpg）
    - public_id（後処理用）
    を返す。
    """
    _init_cloudinary()

    upload_opts = {
        "resource_type": "video",
        "folder": folder,
        "overwrite": True,
        "use_filename": True,
        "unique_filename": True,
    }
    if public_id:
        upload_opts["public_id"] = public_id

    res = cloudinary.uploader.upload(file_path, **upload_opts)
    video_url = res["secure_url"]
    public_id = res["public_id"]

    logger.info(f"Cloudinary uploaded: public_id={public_id}")
    logger.info(f"Cloudinary URL: {video_url}")  # ← URLを表示

    thumb_url, _ = cloudinary_url(
        public_id,
        resource_type="video",
        format="jpg",
        transformation=[{"so": str(thumbnail_sec)}],
        secure=True,
    )
    return video_url, thumb_url, public_id
