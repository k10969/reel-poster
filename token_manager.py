# token_manager.py
import os, re, json, time, logging
from pathlib import Path
import requests

LOG = logging.getLogger("token_manager")

REFRESH_WINDOW_SECONDS = 24 * 3600  # 1日に1回だけ更新を試みる
STATE_FILE = os.getenv("IG_TOKEN_STATE_FILE", "token_state.json")

def _load_state(path: str) -> dict:
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def _save_state(path: str, data: dict) -> None:
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def _replace_line_in_env(env_path: str, key: str, new_value: str) -> None:
    p = Path(env_path)
    if not p.exists():
        # 新規作成
        p.write_text(f"{key}={new_value}\n", encoding="utf-8")
        return
    lines = p.read_text(encoding="utf-8").splitlines()
    pattern = re.compile(rf"^{re.escape(key)}\s*=")
    replaced = False
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = f"{key}={new_value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}={new_value}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")

def refresh_long_lived_token(token: str) -> dict:
    """
    Instagram Long-Lived User Access Token を延長。
    成功すると {access_token, token_type, expires_in} を返す。
    """
    url = "https://graph.instagram.com/refresh_access_token"
    params = {"grant_type": "ig_refresh_token", "access_token": token}
    LOG.info("Refreshing IG long-lived token via %s", url)
    r = requests.get(url, params=params, timeout=30)
    LOG.info("Refresh status=%s", r.status_code)
    r.raise_for_status()
    return r.json()

def ensure_fresh_token(
    env_token: str,
    env_file_path: str = ".env",
    force: bool = False
) -> str:
    """
    必要に応じてトークンを自動延長して .env を更新する。
    - 直近の更新から24時間以内はスキップ（force=Trueで無視）
    - 成功時は新しいトークンを返す
    - 失敗したら元のトークンを返す（ログに残す）
    """
    state = _load_state(STATE_FILE)
    now = time.time()
    last_ts = float(state.get("last_refresh_ts", 0))
    if not force and (now - last_ts) < REFRESH_WINDOW_SECONDS:
        LOG.info("Skip refresh (last %.1f h ago)", (now - last_ts) / 3600.0)
        return env_token

    try:
        data = refresh_long_lived_token(env_token)
        new_token = data.get("access_token")
        expires_in = data.get("expires_in")
        if new_token:
            _replace_line_in_env(env_file_path, "IG_ACCESS_TOKEN", new_token)
            state.update({"last_refresh_ts": now, "expires_in": expires_in})
            _save_state(STATE_FILE, state)
            LOG.info("Token refreshed. expires_in=%s sec", expires_in)
            return new_token
        else:
            LOG.warning("No access_token in refresh response: %s", data)
            return env_token
    except Exception as e:
        LOG.exception("Token refresh failed: %s", e)
        return env_token
