# tokens_bulk.py
import os, json, time, logging, argparse
from logging.handlers import RotatingFileHandler
from pathlib import Path
import requests
from dotenv import load_dotenv

BASE = Path(__file__).parent.resolve()
ACCOUNTS = BASE / "accounts.json"
LOGS = BASE / "logs"; LOGS.mkdir(exist_ok=True)
load_dotenv(BASE / ".env", override=False)

APP_ID = os.getenv("FB_APP_ID")
APP_SECRET = os.getenv("FB_APP_SECRET")

def _log_setup():
    root = logging.getLogger()
    if root.handlers: return
    root.setLevel(logging.INFO)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s"))
    root.addHandler(ch)
    fh = RotatingFileHandler(LOGS / "token_maintenance.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    root.addHandler(fh)

def _need_app_creds():
    if not (APP_ID and APP_SECRET):
        raise RuntimeError("FB_APP_ID / FB_APP_SECRET が .env に未設定です")

def load_accounts():
    if not ACCOUNTS.exists():
        return {"default_account_no": 1, "accounts": []}
    return json.loads(ACCOUNTS.read_text(encoding="utf-8"))

def save_accounts(data, dry=False):
    if dry:
        logging.info("[DRY-RUN] 変更は保存しません")
        return
    ACCOUNTS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def app_access_token():
    r = requests.get("https://graph.facebook.com/v22.0/oauth/access_token", params={
        "client_id": APP_ID, "client_secret": APP_SECRET, "grant_type": "client_credentials"
    }, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]

def debug_token(token, app_token):
    r = requests.get("https://graph.facebook.com/debug_token",
        params={"input_token": token, "access_token": app_token}, timeout=30)
    r.raise_for_status()
    return r.json().get("data", {})

def exchange_to_long_user(short_user_token):
    r = requests.get("https://graph.facebook.com/v22.0/oauth/access_token", params={
        "grant_type":"fb_exchange_token", "client_id":APP_ID, "client_secret":APP_SECRET,
        "fb_exchange_token": short_user_token
    }, timeout=30)
    r.raise_for_status()
    return r.json()  # {access_token, token_type, expires_in}

def list_pages(long_user_token):
    r = requests.get("https://graph.facebook.com/v22.0/me/accounts",
        params={"fields":"id,name,access_token","access_token": long_user_token}, timeout=30)
    r.raise_for_status()
    return r.json().get("data", [])

def page_token_from_page_id(page_id, any_token):
    r = requests.get(f"https://graph.facebook.com/v22.0/{page_id}",
        params={"fields":"access_token","access_token": any_token}, timeout=30)
    r.raise_for_status()
    return r.json().get("access_token","")

def ig_user_from_page(page_id, token):
    r = requests.get(f"https://graph.facebook.com/v22.0/{page_id}",
        params={"fields":"instagram_business_account{id,username}","access_token": token}, timeout=30)
    r.raise_for_status()
    d = r.json().get("instagram_business_account") or {}
    return d.get("id"), d.get("username")

def is_expiring_soon(token_info, days=45):
    exp = token_info.get("expires_at")
    if not exp:
        return True
    return (exp - time.time()) < days*24*3600

def bulk_update(mode="page", dry=False):
    """
    mode:
      - "user_long": 短期ユーザー → 長期ユーザー(EAA)に交換
      - "page":      上に加えてページトークン化（page_idがあればそれを優先）
    """
    _need_app_creds()
    data = load_accounts()
    accs = data.get("accounts", [])
    if not accs:
        logging.info("accounts.json にアカウントがありません")
        return

    app_tok = app_access_token()
    changed = 0
    for a in accs:
        no = a.get("no")
        label = a.get("label","")
        token = a.get("access_token","")
        if not token:
            logging.warning("No.%s (%s): access_token 未設定 → スキップ", no, label); continue

        # 現状トークン情報
        try:
            info = debug_token(token, app_tok)
        except Exception as e:
            logging.warning("No.%s (%s): debug_token失敗 → スキップ (%s)", no, label, e); continue
        ttype = info.get("type")  # USER / PAGE / APP など
        logging.info("No.%s (%s): token type=%s, expires_at=%s", no, label, ttype, info.get("expires_at"))

        # USER → 長期ユーザーへ
        long_user_token = None
        if ttype == "USER":
            if is_expiring_soon(info, days=45) or mode in ("user_long","page"):
                try:
                    out = exchange_to_long_user(token)
                    long_user_token = out.get("access_token")
                    if long_user_token:
                        a["access_token"] = long_user_token
                        a["expires_in"] = int(out.get("expires_in") or 0)
                        changed += 1
                        logging.info("No.%s: 長期ユーザートークンに更新(EAA…)", no)
                    else:
                        logging.warning("No.%s: 長期化レスポンスに token なし", no)
                except Exception as e:
                    logging.warning("No.%s: 長期化に失敗: %s", no, e)

        # ページトークン化
        if mode == "page":
            # 参照トークン（長期ユーザーがあればそれ、なければ元の）
            ref_token = long_user_token or a.get("access_token") or token
            page_id = a.get("page_id")
            if not page_id:
                # page_id未設定 → つながってるページ一覧から推測（IG連携済ページを優先）
                try:
                    pages = list_pages(ref_token)
                except Exception as e:
                    logging.warning("No.%s: ページ一覧取得失敗: %s", no, e); continue
                target = None
                if a.get("ig_user_id"):
                    for p in pages:
                        try:
                            igid, _ = ig_user_from_page(p["id"], ref_token)
                            if igid and str(igid) == str(a["ig_user_id"]):
                                target = p; break
                        except Exception:
                            continue
                if not target and pages:
                    target = pages[0]  # 先頭採用（必要ならGUIでpage_idを手入力して更新してね）
                if not target:
                    logging.warning("No.%s: リンク済みページが見つからず → スキップ", no); continue
                page_id = target["id"]
                a["page_id"] = page_id
                logging.info("No.%s: page_id=%s を設定", no, page_id)

            try:
                ptoken = page_token_from_page_id(page_id, ref_token)
                if ptoken:
                    a["access_token"] = ptoken
                    a["token_type"] = "PAGE"
                    changed += 1
                    logging.info("No.%s: ページトークンに更新", no)
                    igid, uname = ig_user_from_page(page_id, ptoken)
                    if igid:
                        a["ig_user_id"] = str(igid)
                        a["ig_username"] = uname
                else:
                    logging.warning("No.%s: ページトークン取得失敗（空）", no)
            except Exception as e:
                logging.warning("No.%s: ページトークン取得失敗: %s", no, e)

    if changed:
        save_accounts(data, dry)
    logging.info("完了: %s 件更新（mode=%s, dry=%s）", changed, mode, dry)

if __name__ == "__main__":
    _log_setup()
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["user_long","page"], default="page",
                    help="user_long=長期ユーザー化, page=ページトークン化（既定）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    bulk_update(mode=args.mode, dry=args.dry_run)