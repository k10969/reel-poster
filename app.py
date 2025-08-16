# -*- coding: utf-8 -*-
from flask import Flask, render_template, request, jsonify, send_from_directory
from pathlib import Path
import json, os, shutil, traceback, random

# ---- 既存クラスをそのまま使う（Python3.9対応版を置いてある前提）----
from poster_core_reel import PosterCoreReel   # ← 既に直下に置いたやつ
import poster_core_reel_graph_accounts as igpub  # 既存のアカウント管理で使う想定

app = Flask(__name__, static_folder="static", template_folder="templates")

BASE = Path(__file__).parent.resolve()
OVERLAY_DIR = BASE / "overlay_input"
OUTPUT_DIR = BASE / "static" / "output"
BG_DIR = BASE / "static" / "backgrounds"
ORDERS_JSON = BASE / "materials_order.json"
OVERRIDES_JSON = BASE / "material_overrides.json"
RANDOM_TEXTS = BASE / "random_texts.txt"

for p in (OVERLAY_DIR, OUTPUT_DIR, BG_DIR):
    p.mkdir(parents=True, exist_ok=True)

# -------------------- ページ --------------------
@app.get("/")
def index():
    return render_template("index.html")

# -------------------- アカウント --------------------
@app.get("/api/accounts")
def api_accounts():
    # poster_core_reel_graph_accounts.py が持っているアカウント配列をそのまま返す体裁
    try:
        arr = []
        for i, acc in enumerate(getattr(igpub, "ACCOUNTS", []), start=1):
            arr.append({
                "no": i,
                "label": acc.get("label") or f"account_{i}",
                "ig_user_id": acc.get("ig_user_id", ""),
                "page_id": acc.get("page_id", "")
            })
        return jsonify(arr)
    except Exception as e:
        return jsonify([])

# -------------------- 素材一覧 --------------------
@app.get("/api/materials")
def api_materials():
    # 並び順
    order = []
    if ORDERS_JSON.exists():
        try:
            order = json.loads(ORDERS_JSON.read_text("utf-8"))
        except Exception:
            order = []

    # テキスト上書き
    overrides = {}
    if OVERRIDES_JSON.exists():
        try:
            overrides = json.loads(OVERRIDES_JSON.read_text("utf-8"))
        except Exception:
            overrides = {}

    files = []
    for p in OVERLAY_DIR.iterdir():
        if not p.is_file():
            continue
        files.append(p.name)

    # 並び順適用（orderにない新規は後ろに）
    if order:
        ordered = [n for n in order if n in files] + [n for n in files if n not in order]
    else:
        ordered = sorted(files)

    items = []
    for name in ordered:
        items.append({
            "name": name,
            "url": f"/overlay/{name}",
            "text": overrides.get(name) or ""
        })
    return jsonify(items)

@app.get("/overlay/<path:name>")
def overlay_file(name):
    return send_from_directory(OVERLAY_DIR, name)

# -------------------- アップロード/削除 --------------------
@app.post("/api/upload")
def api_upload():
    fs = request.files.getlist("files")
    if not fs:
        return "no files", 400
    for f in fs:
        dst = OVERLAY_DIR / f.filename
        f.save(dst)
    return "ok"

@app.post("/api/remove")
def api_remove():
    data = request.get_json(force=True)
    names = data.get("names") or []
    # override も掃除
    overrides = {}
    if OVERRIDES_JSON.exists():
        try: overrides = json.loads(OVERRIDES_JSON.read_text("utf-8"))
        except: overrides = {}
    for n in names:
        try: (OVERLAY_DIR / n).unlink(missing_ok=True)
        except: pass
        if n in overrides: overrides.pop(n, None)
    OVERRIDES_JSON.write_text(json.dumps(overrides, ensure_ascii=False, indent=2), "utf-8")
    return "ok"

# -------------------- 並び順/テキスト保存 --------------------
@app.post("/api/update_order")
def api_update_order():
    data = request.get_json(force=True)
    order = data.get("order") or []
    ORDERS_JSON.write_text(json.dumps(order, ensure_ascii=False, indent=2), "utf-8")
    return "ok"

@app.post("/api/update_text")
def api_update_text():
    data = request.get_json(force=True)
    name = data.get("name")
    text = (data.get("text") or "").strip()
    overrides = {}
    if OVERRIDES_JSON.exists():
        try: overrides = json.loads(OVERRIDES_JSON.read_text("utf-8"))
        except: overrides = {}
    if text:
        overrides[name] = text
    else:
        overrides.pop(name, None)
    OVERRIDES_JSON.write_text(json.dumps(overrides, ensure_ascii=False, indent=2), "utf-8")
    return "ok"

# -------------------- 投稿実行 --------------------
@app.post("/api/post")
def api_post():
    try:
        data = request.get_json(force=True)
        account_no = int(data.get("account_no") or 1)
        all_accounts = bool(data.get("all_accounts"))
        selected_names = data.get("selected_names") or []

        # 素材一覧（順序適用）
        mats = json.loads(api_materials().get_data())
        if selected_names:
            mats = [m for m in mats if m["name"] in selected_names]

        if not mats:
            return jsonify({"message": "素材がありません"}), 400

        # テキスト上書き
        overrides = {}
        if OVERRIDES_JSON.exists():
            try: overrides = json.loads(OVERRIDES_JSON.read_text("utf-8"))
            except: overrides = {}

        # どのアカウントで行くか
        if all_accounts:
            account_nos = list(range(1, len(getattr(igpub, "ACCOUNTS", []))+1))
        else:
            account_nos = [account_no]

        pcr = PosterCoreReel()

        results = []
        for acc_no in account_nos:
            # 背景は background{no}.mp4 を自動選択
            bg_path = BG_DIR / f"background{acc_no}.mp4"
            if not bg_path.exists():
                # なければ background1.mp4 にフォールバック
                fallback = BG_DIR / "background1.mp4"
                if fallback.exists():
                    bg_path = fallback
                else:
                    return jsonify({"message": f"背景が見つかりません: {bg_path.name}"}), 400

            for m in mats:
                overlay = OVERLAY_DIR / m["name"]
                custom_text = (overrides.get(m["name"]) or "").strip()
                media_id = pcr.post_reel(
                    account_no=acc_no,
                    overlay_path=overlay,
                    background_path=bg_path,
                    custom_overlay_text=custom_text or None,
                    share_to_feed=False,   # “フィードにも共有”したければ True
                )
                results.append({"account": acc_no, "name": m["name"], "media_id": media_id})

        return jsonify({"message":"投稿完了", "results": results})
    except Exception as e:
        tb = traceback.format_exc()
        return f"投稿失敗: {e}\n{tb}", 500

# -------------------- 静的出力 --------------------
@app.get("/output/<path:name>")
def output_file(name):
    return send_from_directory(OUTPUT_DIR, name)

# ------------- dev only -------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=True)
