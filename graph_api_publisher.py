# graph_api_publisher.py
import os
import time
import logging
import requests
from typing import Optional

GRAPH_API = os.getenv("FB_GRAPH_BASE", "https://graph.facebook.com/v22.0")
LOG = logging.getLogger("ig_graph")

class IGGraphError(RuntimeError):
    pass

def get_ig_user_id_from_page(page_id: str, access_token: str) -> str:
    url = f"{GRAPH_API}/{page_id}"
    r = requests.get(url, params={
        "fields": "instagram_business_account{id,username}",
        "access_token": access_token
    }, timeout=30)
    if r.status_code >= 400:
        raise IGGraphError(f"get_ig_user_id_from_page failed: {r.status_code} {r.text}")
    data = r.json()
    ig = data.get("instagram_business_account") or {}
    return ig.get("id", "")

def get_page_token_from_page(page_id: str, user_token: str) -> str:
    url = f"{GRAPH_API}/{page_id}"
    r = requests.get(url, params={"fields": "access_token", "access_token": user_token}, timeout=30)
    if r.status_code >= 400:
        raise IGGraphError(f"get_page_token_from_page failed: {r.status_code} {r.text}")
    return r.json().get("access_token", "")

def create_reels_container(
    ig_user_id: str,
    access_token: str,
    video_url: str,
    caption: str = "",
    cover_url: Optional[str] = None,
    share_to_feed: bool = False,   # ← 既定False（グリッド非表示）
    audio_name: Optional[str] = None,
) -> str:
    """
    正式仕様：
      POST /{ig-user-id}/media
      - media_type=REELS
      - share_to_feed=false でメイングリッド非表示（"false" 文字列で送るのが安定）
    """
    url = f"{GRAPH_API}/{ig_user_id}/media"
    data = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption or "",
        # ← ここがキモ。"false"/"true" を明示の文字列にする
        "share_to_feed": "False" if share_to_feed else "false",
        "access_token": access_token,
    }
    if cover_url:
        data["cover_url"] = cover_url
    if audio_name:
        data["audio_name"] = audio_name

    LOG.info("Payload to /media: %s", {k: (v if k != "access_token" else "***") for k, v in data.items()})
    r = requests.post(url, data=data, timeout=120)
    if r.status_code >= 400:
        raise IGGraphError(f"create_reels_container failed: {r.status_code} {r.text}")
    cid = r.json().get("id")
    if not cid:
        raise IGGraphError(f"Invalid response (no id): {r.text}")
    return cid

def wait_container_finished(
    creation_id: str,
    access_token: str,
    timeout_sec: int = 900,
    poll_sec: float = 4.0
) -> dict:
    url = f"{GRAPH_API}/{creation_id}"
    deadline = time.time() + timeout_sec
    last = {}
    while time.time() < deadline:
        r = requests.get(url, params={"fields": "status,status_code", "access_token": access_token}, timeout=60)
        if r.status_code >= 400:
            raise IGGraphError(f"wait_container_failed: {r.status_code} {r.text}")
        js = r.json()
        last = js
        code = (js.get("status_code") or js.get("status") or "").upper()
        if code == "FINISHED":
            return js
        if code == "ERROR":
            raise IGGraphError(f"Container processing error: {js}")
        time.sleep(poll_sec)
    raise IGGraphError(f"Timeout waiting for container to finish. last={last}")

def publish_container(ig_user_id: str, creation_id: str, access_token: str) -> str:
    """正: POST /{ig-user-id}/media_publish に creation_id を渡す"""
    url = f"{GRAPH_API}/{ig_user_id}/media_publish"
    r = requests.post(url, data={"creation_id": creation_id, "access_token": access_token}, timeout=120)
    if r.status_code >= 400:
        raise IGGraphError(f"publish_container failed: {r.status_code} {r.text}")
    mid = r.json().get("id")
    if not mid:
        raise IGGraphError(f"Invalid publish response: {r.text}")
    return mid
