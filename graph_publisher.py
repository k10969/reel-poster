# graph_publisher.py
import os
import time
import requests

GRAPH_BASE = os.getenv("FACEBOOK_GRAPH_BASE", "https://graph.facebook.com/v21.0")

class GraphError(Exception):
    pass

def _req(method, url, **kw):
    r = requests.request(method, url, timeout=60, **kw)
    if not r.ok:
        raise GraphError(f"{r.status_code}: {r.text}")
    try:
        return r.json()
    except Exception:
        return {"raw": r.text}

def ig_create_container(ig_user_id: str, media_url: str, is_video: bool, caption: str, access_token: str):
    url = f"{GRAPH_BASE}/{ig_user_id}/media"
    data = {"caption": caption or "", "access_token": access_token}
    if is_video:
        # リール投稿
        data["media_type"] = "REELS"
        data["video_url"] = media_url
        data["share_to_feed"] = "true"
    else:
        data["image_url"] = media_url
    return _req("POST", url, data=data)

def ig_publish_container(ig_user_id: str, creation_id: str, access_token: str):
    url = f"{GRAPH_BASE}/{ig_user_id}/media_publish"
    data = {"creation_id": creation_id, "access_token": access_token}
    return _req("POST", url, data=data)

def ig_get_status(creation_id: str, access_token: str):
    url = f"{GRAPH_BASE}/{creation_id}"
    params = {"fields": "status_code,status,permalink", "access_token": access_token}
    return _req("GET", url, params=params)

def ig_post_now(ig_user_id: str, media_url: str, is_video: bool, caption: str, access_token: str,
                poll_sec: int = 8, max_wait: int = 300):
    # 1) コンテナ作成
    c = ig_create_container(ig_user_id, media_url, is_video, caption, access_token)
    creation_id = c.get("id")
    if not creation_id:
        return {"ok": False, "error": c}
    # 2) 公開
    ig_publish_container(ig_user_id, creation_id, access_token)
    # 3) ステータス監視
    waited = 0
    while waited <= max_wait:
        s = ig_get_status(creation_id, access_token)
        code = s.get("status_code") or s.get("status")
        if code in ("FINISHED", "PUBLISHED"):
            return {"ok": True, "creation_id": creation_id, "permalink": s.get("permalink")}
        if code in ("ERROR", "FAILED"):
            return {"ok": False, "error": s}
        time.sleep(poll_sec)
        waited += poll_sec
    return {"ok": False, "error": "timeout"}

