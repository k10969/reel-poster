# app.py - Streamlit版 ReelPosterApp (iPhone対応)
import os
import json
import shutil
import threading
import traceback
import time
import logging
from pathlib import Path
from typing import List
import random
from dotenv import load_dotenv

import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import imageio

from poster_core_reel import PosterCoreReel, SUPPORTED_EXTS
from creds_manager import list_accounts, upsert_account, get_account
from token_status import owner_token_status, TokenError
from poster_core_reel_graph_accounts import post_reel  # 元の投稿関数

# パス設定 (Renderの永続ディスク用: /data にマウント推奨)
DATA_DIR = Path(os.getenv("PERSISTENT_DIR", "."))  # Renderで環境変数設定
SCRIPT_DIR = DATA_DIR
ACCOUNTS_JSON = SCRIPT_DIR / "accounts.json"
ENV_PATH = SCRIPT_DIR / ".env"
RANDOM_TEXT_FILE = SCRIPT_DIR / "random_texts.txt"
OVERRIDES_JSON = SCRIPT_DIR / "material_overrides.json"
ORDER_JSON = SCRIPT_DIR / "material_order.json"
OVERLAY_DIR = SCRIPT_DIR / "overlay_input"
OVERLAY_DIR.mkdir(exist_ok=True)
LOG_DIR = SCRIPT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

load_dotenv(ENV_PATH)

# ロギング
LOG = logging.getLogger("web_reel_poster")
if not LOG.handlers:
    LOG.setLevel(logging.DEBUG)
    fh = logging.FileHandler(LOG_DIR / "web_poster.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    LOG.addHandler(fh)

# サムネ関数 (元のまま)
ROW_H = 144
THUMB_W = 144

def _placeholder(text="VIDEO", w=THUMB_W, h=ROW_H):
    img = Image.new("RGB", (w, h), (34, 34, 34))
    drw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default()
        bbox = drw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        tw, th = 40, 16
        font = None
    drw.rectangle((0, 0, w-1, h-1), outline=(90, 90, 90), width=1)
    drw.text(((w - tw)//2, (h - th)//2), text, fill=(230, 230, 230), font=font)
    return img

def _thumb_from_image(path: Path):
    try:
        im = Image.open(path).convert("RGB")
        im.thumbnail((THUMB_W, ROW_H))
        canvas = Image.new("RGB", (THUMB_W, ROW_H), (34, 34, 34))
        x = (THUMB_W - im.width)//2
        y = (ROW_H - im.height)//2
        canvas.paste(im, (x, y))
        return canvas
    except Exception:
        return _placeholder("IMG ERR")

def _thumb_from_video(path: Path):
    try:
        reader = imageio.get_reader(str(path))
        frm = reader.get_data(0)
        reader.close()
        im = Image.fromarray(frm).convert("RGB")
        im.thumbnail((THUMB_W, ROW_H))
        canvas = Image.new("RGB", (THUMB_W, ROW_H), (34, 34, 34))
        x = (THUMB_W - im.width)//2
        y = (ROW_H - im.height)//2
        canvas.paste(im, (x, y))
        return canvas
    except Exception:
        return _placeholder("VIDEO")

# JSON I/O関数 (元のまま)
def _load_overrides() -> dict:
    if OVERRIDES_JSON.exists():
        return json.loads(OVERRIDES_JSON.read_text(encoding="utf-8"))
    return {}

def _save_overrides(data: dict):
    OVERRIDES_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def _load_order_list() -> List[str]:
    if ORDER_JSON.exists():
        raw = json.loads(ORDER_JSON.read_text(encoding="utf-8"))
        return raw.get("order", []) if isinstance(raw, dict) else raw
    return []

def _save_order_list(names: List[str]):
    ORDER_JSON.write_text(json.dumps({"order": names}, ensure_ascii=False, indent=2), encoding="utf-8")

def _save_accounts_json(data: dict):
    ACCOUNTS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def _delete_account(no: int):
    data = json.loads(ACCOUNTS_JSON.read_text(encoding="utf-8")) if ACCOUNTS_JSON.exists() else {"accounts": []}
    data["accounts"] = [a for a in data.get("accounts", []) if a.get("no") != no]
    _save_accounts_json(data)

# Streamlitメインアプリ
def main():
    st.set_page_config(page_title="Reel Poster", layout="wide")  # ワイドレイアウトでGUI近似

    # 簡易認証 (iPhone対応: パスワード入力)
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if not st.session_state.authenticated:
        pw = st.text_input("パスワード", type="password")
        if pw == os.getenv("APP_PASSWORD", "default_pw"):  # .envで設定
            st.session_state.authenticated = True
            st.rerun()
        return

    # 状態初期化
    if "materials" not in st.session_state:
        st.session_state.materials = []
        st.session_state.selected_mats = []
        st.session_state.accounts = list_accounts()
        st.session_state.all_accounts = False
        st.session_state.stop_flag = False
        st.session_state.progress = 0.0
        st.session_state.log_text = ""

    # レイアウト: 2列 (左コントロール, 右リスト/ログ) - 元GUI近似
    col1, col2 = st.columns([1, 2])

    with col1:
        st.header("アカウント管理")
        acc_options = [f"No.{a['no']} {a.get('label', '')}" for a in st.session_state.accounts]
        selected_acc = st.selectbox("アカウント選択", acc_options, index=0)
        st.session_state.all_accounts = st.checkbox("全アカウント", value=st.session_state.all_accounts)

        st.subheader("アカウント追加/更新")
        number = st.number_input("番号", min_value=1, value=1)
        label = st.text_input("ラベル")
        igid = st.text_input("IGユーザーID")
        page = st.text_input("ページID")
        if st.button("登録/更新"):
            upsert_account(number, label, igid, "")  # tokenは空でOK
            st.session_state.accounts = list_accounts()
            st.success(f"No.{number} 更新")

        if st.button("削除"):
            if selected_acc and not st.session_state.all_accounts:
                no = int(selected_acc.split()[0].replace("No.", ""))
                _delete_account(no)
                st.session_state.accounts = list_accounts()
                st.success("削除完了")
            else:
                st.error("アカウントを選択、全OFFに")

        st.subheader("トークン")
        if st.button("トークン更新"):
            new_token = st.text_input("新しいトークン", type="password")
            if new_token:
                # .env更新 (Render環境変数手動更新推奨)
                with open(ENV_PATH, "a") as f:
                    f.write(f"OWNER_USER_TOKEN={new_token}\n")
                st.success("更新完了")
        if st.button("トークン確認"):
            try:
                status = owner_token_status(os.getenv("OWNER_USER_TOKEN"))
                st.info(f"種類: {status['type']}\n有効: {status['is_valid']}\n残り日数: {status['remaining_days']}")
            except TokenError as e:
                st.error(str(e))

        st.header("投稿設定")
        custom_text = st.text_input("オーバーレイテキスト (空でランダム)")
        if st.button("投稿開始"):
            if st.session_state.selected_mats:
                threading.Thread(target=_post_thread, args=(st.session_state.selected_mats, custom_text)).start()
            else:
                st.error("素材を選択")
        if st.button("停止"):
            st.session_state.stop_flag = True

    with col2:
        st.header("素材リスト")
        # アップロード (DnD代替: 複数選択, iPhone対応)
        uploaded = st.file_uploader("素材アップロード", type=list(SUPPORTED_EXTS), accept_multiple_files=True)
        if uploaded:
            for file in uploaded:
                path = OVERLAY_DIR / file.name
                path.write_bytes(file.getvalue())
            _refresh_materials()

        # リスト表示 (サムネ + チェックボックス)
        def _refresh_materials():
            files = list(OVERLAY_DIR.glob("*"))  # フィルタ省略
            order = _load_order_list()
            files.sort(key=lambda f: order.index(f.name) if f.name in order else len(order))
            st.session_state.materials = files

        _refresh_materials()
        selected = []
        for mat in st.session_state.materials:
            c1, c2 = st.columns([0.3, 0.7])
            with c1:
                if mat.suffix.lower() in {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}:
                    thumb = _thumb_from_image(mat)
                else:
                    thumb = _thumb_from_video(mat)
                st.image(thumb)
            with c2:
                if st.checkbox(mat.name):
                    selected.append(mat)
        st.session_state.selected_mats = selected

        st.subheader("ログ")
        st.text_area("ログ", st.session_state.log_text, height=150)
        st.progress(st.session_state.progress)

# 投稿スレッド (バックグラウンド, UI更新)
def _post_thread(mats: List[Path], custom_text: str):
    core = PosterCoreReel()
    total = len(mats)
    for i, mat in enumerate(mats):
        if st.session_state.stop_flag:
            break
        st.session_state.progress = (i + 1) / total
        try:
            acc_nos = [a["no"] for a in st.session_state.accounts] if st.session_state.all_accounts else [int(selected_acc.split()[0].replace("No.", ""))]
            for no in acc_nos:
                media_id = core.post_reel(no, mat, Path("background.mp4"), custom_text)  # backgroundは仮定
                st.session_state.log_text += f"投稿成功: {mat.name} to No.{no} (ID: {media_id})\n"
        except Exception as e:
            st.session_state.log_text += f"エラー: {mat.name} {traceback.format_exc()}\n"
        st.rerun()  # UI更新

if __name__ == "__main__":
    main()
