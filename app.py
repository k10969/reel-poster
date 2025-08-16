from flask import Flask, request, jsonify, render_template
import traceback
import os
from pathlib import Path
from poster_core_reel import PosterCoreReel
import json

# ===== Flask インスタンス =====
app = Flask(__name__)

# ===== 基本パス設定 =====
BASE_DIR = Path(__file__).parent.resolve()
ACCOUNTS_FILE = BASE_DIR / "accounts.json"

# ===== 背景動画の解決関数 =====
def resolve_background_path(account_no: int) -> Path:
    """background<no>.mp4 と no.mp4 の両方に対応"""
    candidates = [
        BASE_DIR / "static" / "backgrounds" / f"background{account_no}.mp4",
        BASE_DIR / "static" / "backgrounds" / f"{account_no}.mp4",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        f"背景が見つかりません。試したパス: {', '.join(str(c) for c in candidates)}"
    )

# ===== アカウント読み込み =====
def load_accounts():
    if not ACCOUNTS_FILE.exists():
        return []
    try:
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("accounts", [])
    except Exception as e:
        print("accounts.json 読み込みエラー:", e)
        return []

# ===== トップページ =====
@app.route("/")
def index():
    try:
        accounts = load_accounts()
        return render_template("index.html", accounts=accounts)
    except Exception as e:
        return f"初期化エラー: {e}"

# ===== 動画生成＋投稿API =====
@app.route("/generate_and_post", methods=["POST"])
def generate_and_post():
    try:
        account_no = int(request.form.get("account_no"))
        overlay_file = request.files.get("overlay_file")
        custom_text = request.form.get("custom_text") or None

        if not overlay_file:
            return jsonify({"error": "素材ファイルが選択されていません"}), 400

        # 一時保存
        overlay_path = BASE_DIR / "static" / "uploads" / overlay_file.filename
        overlay_file.save(overlay_path)

        # 背景動画パス取得
        background_path = resolve_background_path(account_no)

        # 動画生成＆投稿
        core = PosterCoreReel()
        media_id = core.post_reel(
            account_no=account_no,
            overlay_path=overlay_path,
            background_path=background_path,
            custom_overlay_text=custom_text,
            share_to_feed=False
        )

        return jsonify({"success": True, "media_id": media_id})

    except Exception as e:
        tb = traceback.format_exc()
        print("投稿エラー:", tb)
        return jsonify({"error": str(e), "traceback": tb}), 500

# ===== ヘルスチェック =====
@app.route("/health")
def health():
    return "OK", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
