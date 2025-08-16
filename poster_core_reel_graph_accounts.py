import os
import logging
import time
import random
from logging.handlers import RotatingFileHandler
from pathlib import Path
from dotenv import load_dotenv

from cloudinary_uploader import upload_video_get_urls
from graph_api_publisher import (
    create_reels_container, wait_container_finished, publish_container,
    IGGraphError, get_ig_user_id_from_page, get_page_token_from_page
)
from token_status import debug_token
from creds_manager import get_account

LOG = logging.getLogger("ig_poster_accounts")
_LOG_READY = False

BASE_DIR = Path(__file__).parent.resolve()
load_dotenv(BASE_DIR / ".env", override=False)
MASTER_USER_TOKEN = os.getenv("OWNER_USER_TOKEN", "")

def _setup_logging(log_file: str = "logs/ig_poster.log"):
    global _LOG_READY
    if _LOG_READY:
        return
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s"))
    root.addHandler(ch)
    fh = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    root.addHandler(fh)
    _LOG_READY = True

def _maybe_refresh_token(token: str, *_, **__) -> str:
    return token  # ページトークンは都度取得なので延長なし

def post_reel(
    video_path: str | None = None,
    video_url: str | None = None,
    cover_url: str | None = None,
    account_no: int = 1,
    force_refresh: bool = False,
    log_file: str = "logs/ig_poster.log",
    caption: str = "",  # ← デフォルト値を追加し、最後に移動
) -> str:
    """指定アカウント番号でリール投稿。成功すると media_id を返す。"""
    _setup_logging(log_file)

    acc = get_account(account_no)
    if not acc:
        raise IGGraphError(f"accounts.json にアカウント no={account_no} が見つかりません")

    page_id = acc.get("page_id")
    ig_user_id_saved = acc.get("ig_user_id")
    saved_token = acc.get("access_token", "")

    if not page_id:
        raise IGGraphError("page_id が未設定です（共通トークン運用では必須）")

    base_token = MASTER_USER_TOKEN or saved_token
    if not base_token:
        raise IGGraphError("OWNER_USER_TOKEN が .env にありません。『トークン更新』から設定してください。")
    access_token = get_page_token_from_page(page_id, base_token)
    if not access_token:
        raise IGGraphError("ページトークンを取得できませんでした。権限/リンクを確認してください。")

    try:
        info = debug_token(access_token)
        LOG.info("Token type=%s app_id=%s user_id=%s", info.get("type"), info.get("app_id"), info.get("user_id"))
        if info.get("type") != "PAGE":
            raise IGGraphError(f"ページトークン取得に失敗: token_type={info.get('type')}")
    except Exception as e:
        LOG.warning("debug_token failed or not PAGE: %s", e)

    fresh_token = _maybe_refresh_token(access_token, account_no)
    ig_user_id_live = get_ig_user_id_from_page(page_id, fresh_token)
    if not ig_user_id_live:
        raise IGGraphError("page_id から IGユーザーID を取得できませんでした。IGリンク/権限を確認してください。")
    if ig_user_id_saved and ig_user_id_saved != ig_user_id_live:
        LOG.warning("IG_USER_ID mismatch: saved=%s live=%s -> liveを採用", ig_user_id_saved, ig_user_id_live)
    ig_user_id = ig_user_id_live

    # Cloudinaryアップロード: video_url/cover_urlが未指定の場合のみ実行
    if not video_url or not cover_url:
        if not video_path:
            raise IGGraphError("video_path または (video_url, cover_url) のいずれかを指定してください")
        LOG.info("Uploading to Cloudinary...")
        video_url, cover_url, public_id = upload_video_get_urls(video_path, thumbnail_sec=1.0)
        LOG.info("Cloudinary uploaded: public_id=%s", public_id)
        LOG.info("Cloudinary URL: %s", video_url)
    else:
        LOG.info("Using provided Cloudinary URLs: video=%s, cover=%s", video_url, cover_url)
        public_id = "pre-uploaded"  # ログ用ダミー

    LOG.info("Creating IG container...")
    creation_id = create_reels_container(
        ig_user_id=ig_user_id,
        access_token=fresh_token,
        video_url=video_url,
        caption=caption,
        cover_url=cover_url,
        share_to_feed=False
    )
    LOG.info("Creation ID=%s", creation_id)

    LOG.info("Waiting container to finish...")
    status = wait_container_finished(creation_id, fresh_token, timeout_sec=900, poll_sec=4)
    LOG.info("Container finished: %s", status)

    LOG.info("Publishing...")
    media_id = publish_container(ig_user_id, creation_id, fresh_token)
    LOG.info("Published media_id=%s", media_id)

    # レート制限回避のため、投稿後に2〜5秒のランダム待機
    sleep_time = random.uniform(2.0, 5.0)
    LOG.info("Sleeping for %.2f seconds to avoid rate limits", sleep_time)
    time.sleep(sleep_time)

    return media_id
