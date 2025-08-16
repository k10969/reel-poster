# poster_core_reel_graph_accounts.py — Py3.9互換 / Instagram Reels 投稿（URLベース）
from __future__ import annotations
import json
import time
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, Dict, Any

import requests

# ------------- ログ設定 -------------
BASE_DIR: Path = Path(__file__).resolve().parent
LOG_DIR: Path = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOG = logging.getLogger("ig_graph_publisher")
if not LOG.handlers:
    LOG.setLevel(logging.INFO)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s"))
    LOG.addHandler(ch)
    fh = RotatingFileHandler(LOG_DIR / "ig_publisher.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    LOG.addHandler(fh)

# ------------- 設定/アカウント読込 -------------
ACCOUNTS_JSON: Path = BASE_DIR / "accounts.json"
GRAPH_VER = "v20.0"   # APIバージョン（必要に応じて合わせてOK）

def _load_accounts() -> Dict[str, Any]:
    # settings_store があれば優先（ない場合は accounts.json を直読）
    try:
        from settings_store import load_accounts  # type: ignore
        data = load_accounts()
        if isinstance(data, dict) and "accounts" in data:
            return data
    except Exception:
        pass

    if not ACCOUNTS_JSON.exists():
        return {"accounts": []}
    try:
        txt = ACCOUNTS_JSON.read_text(encoding="utf-8")
        if not txt.strip():
            return {"accounts": []}
        d = json.loads(txt)
        if isinstance(d, dict) and "accounts" in d:
            return d
    except Exception as e:
        LOG.warning("accounts.json 読み込み失敗: %s", e)
    return {"accounts": []}

def _get_account_by_no(account_no: int) -> Optional[Dict[str, str]]:
    data = _load_accounts()
    for a in data.get("accounts", []):
        try:
            if str(a.get("no", "")).strip() == str(account_no):
                return {
                    "no": str(a.get("no", "")).strip(),
                    "label": str(a.get("label", "")),
                    "ig_user_id": str(a.get("ig_user_id", "")),
                    "page_id": str(a.get("page_id", "")),
                    "access_token": str(a.get("access_token", "")),
                }
        except Exception:
            continue
    return None

# ------------- Graph API 呼び出し -------------
def _graph_post(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    r = requests.post(url, data=params, timeout=60)
    try:
        js = r.json()
    except Exception:
        js = {"_raw": r.text}
    if r.status_code >= 400:
        raise RuntimeError(f"Graph POST {url} {r.status_code}: {js}")
    return js

def _graph_get(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    r = requests.get(url, params=params, timeout=60)
    try:
        js = r.json()
    except Exception:
        js = {"_raw": r.text}
    if r.status_code >= 400:
        raise RuntimeError(f"Graph GET {url} {r.status_code}: {js}")
    return js

# ------------- 公開API -------------
def post_reel(
    video_url: str,
    cover_url: Optional[str],
    caption: str,
    account_no: int,
    force_refresh: bool = False,
    log_file: Optional[str] = None,
    share_to_feed: bool = False,
) -> str:
    """
    Cloudinary などに上がっている video_url を使って Reels を投稿する。
    1) /{ig_user_id}/media に video_url 等を投げてコンテナ作成
    2) status_code=FINISHED までポーリング
    3) /{ig_user_id}/media_publish で公開
    戻り値: 公開されたメディアID（文字列）
    """
    if log_file:
        try:
            fh2 = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
            fh2.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
            LOG.addHandler(fh2)
        except Exception:
            pass

    acct = _get_account_by_no(account_no)
    if not acct:
        raise RuntimeError(f"accounts.json にアカウント no={account_no} が見つかりません")

    ig_user_id = acct["ig_user_id"]
    access_token = acct["access_token"]
    if not ig_user_id or not access_token:
        raise RuntimeError("ig_user_id または access_token が空です")

    LOG.info("IG reels upload start: account_no=%s, ig_user_id=%s", account_no, ig_user_id)

    # --- 1) コンテナ作成 ---
    media_ep = f"https://graph.facebook.com/{GRAPH_VER}/{ig_user_id}/media"
    params: Dict[str, Any] = {
        "media_type": "REELS",          # Reels 指定
        "video_url": video_url,
        "caption": caption or "",
        "access_token": access_token,
    }
    # cover（サムネ）URLを渡せる場合
    if cover_url:
        params["cover_url"] = cover_url
    # フィードにも共有するか
    if share_to_feed:
        params["share_to_feed"] = "true"

    create_res = _graph_post(media_ep, params)
    creation_id = str(create_res.get("id", "")).strip()
    if not creation_id:
        raise RuntimeError(f"media コンテナ作成に失敗: {create_res}")
    LOG.info("media container created: %s", creation_id)

    # --- 2) ステータス監視 ---
    status_ep = f"https://graph.facebook.com/{GRAPH_VER}/{creation_id}"
    # 最大待ち時間・ポーリング間隔（必要に応じ調整）
    deadline = time.time() + 15 * 60  # 15分
    interval = 5.0

    last_status = None
    while time.time() < deadline:
        st = _graph_get(status_ep, params={"fields": "status_code", "access_token": access_token})
        status_code = str(st.get("status_code", "")).upper()
        if status_code and status_code != last_status:
            LOG.info("container status: %s", status_code)
            last_status = status_code

        if status_code in ("FINISHED", "PUBLISHED"):
            break
        if status_code in ("ERROR", "FAILED"):
            raise RuntimeError(f"コンテナ処理失敗: {st}")
        time.sleep(interval)
    else:
        raise TimeoutError("コンテナ処理がタイムアウトしました")

    # --- 3) 公開 ---
    publish_ep = f"https://graph.facebook.com/{GRAPH_VER}/{ig_user_id}/media_publish"
    pub_res = _graph_post(publish_ep, params={"creation_id": creation_id, "access_token": access_token})
    media_id = str(pub_res.get("id", "")).strip()
    if not media_id:
        raise RuntimeError(f"公開失敗: {pub_res}")

    LOG.info("media published: %s", media_id)
    return media_id


# ------------- テスト用（ローカルのみ）-------------
if __name__ == "__main__":
    # 簡易テスト（環境により実行不可の場合あり）
    # python poster_core_reel_graph_accounts.py
    import sys
    if len(sys.argv) < 5:
        print("Usage: python poster_core_reel_graph_accounts.py <account_no> <video_url> <cover_url_or_- > <caption>")
        sys.exit(0)

    no = int(sys.argv[1])
    vurl = sys.argv[2]
    curl = None if sys.argv[3] == "-" else sys.argv[3]
    cap = " ".join(sys.argv[4:])

    try:
        mid = post_reel(video_url=vurl, cover_url=curl, caption=cap, account_no=no, share_to_feed=False)
        print("OK:", mid)
    except Exception as e:
        print("ERR:", e)
        sys.exit(1)
