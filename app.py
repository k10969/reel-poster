# -*- coding: utf-8 -*-
from flask import Flask, render_template, request, jsonify, send_from_directory
from pathlib import Path
import json, os, shutil, traceback, random, typing as t

from poster_core_reel import PosterCoreReel
import poster_core_reel_graph_accounts as igpub

app = Flask(__name__, static_folder="static", template_folder="templates")

BASE = Path(__file__).parent.resolve()
OVERLAY_DIR = BASE / "overlay_input"
OUTPUT_DIR  = BASE / "static" / "output"
BG_DIR      = BASE / "static" / "backgrounds"
ACCOUNTS_JSON = BASE / "accounts.json"
ORDERS_JSON   = BASE / "materials_order.json"
OVERRIDES_JSON= BASE / "material_overrides.json"
RANDOM_TEXTS  = BASE / "random_texts.txt"

for p in (OVERLAY_DIR, OUTPUT_DIR, BG_DIR):
    p.mkdir(parents=True, exist_ok=True)

# -------------------- accounts.json ローダ --------------------
def _normalize_accounts(obj: t.Any) -> t.List[dict]:
    """
    受け取ったJSONを [ {label, ig_user_id, page_id, ...}, ... ] に正規化
    - 配列
    - {"accounts":[...]}
    - {"acc1": {...}, "acc2": {...}} の辞書
    に対応
    """
    if isinstance(obj, list):
        raw_list = obj
    elif isinstance(obj, dict):
        if "accounts" in obj and isinstance(obj["accounts"], list):
            raw_list = obj["accounts"]
        else:
            # 値が辞書のパターン
            raw_list = list(obj.values())
    else:
        return []

    out = []
    for i, a in enumerate(raw_list, start=1):
        if not isinstance(a, dict):
            continue
        out.append({
            "label": a.get("label") or a.get("name") or f"account_{i}",
            "ig_user_id": a.get("ig_user_id") or a.get("igUserId") or "",
            "page_id": a.get("page_id") or a.get("pageId") or "",
            # 必要なら他のフィールドも温存
            **{k:v for k,v in a.items() if k not in ("label","name","ig_user_id","igUserId","page_id","pageId")}
        })
    return out

def load_accounts() -> t.List[dict]:
    # 1) accounts.json 優先
    if ACCOUNTS_JSON.exists():
        try:
            data = json.loads(ACCOUNTS_JSON.read_text("utf-8"))
            accs = _normalize_accounts(data)
            if accs:
                return accs
        except Exception:
            pass
    # 2) フォールバック: 既存の igpub.ACCOUNTS
    accs = []
    for i, a in enumerate(getattr(igpub, "ACCOUNTS", []), start=1):
        accs.append({
            "label": a.get("label") or f"account_{i}",
            "ig_user_id": a.get("ig_user_id", ""),
            "page_id": a.get("page_id", "")
        })
    return accs

# -------------------- random text --------------------
def get_random_text() -> str:
    if RANDOM_TEXTS.exists():
        lines = [ln.strip() for ln in RANDOM_TEXTS.read_text("utf-8", errors="ignore").splitlines()]
        lines = [ln for ln in lines if ln]
        if lines:
            return random.choice(lines)
    return ""

# -------------------- ページ --------------------
@app.get("/")
def index():
    return render_template("index.html")

# -------------------- アカウント --------------------
@app.get("/api/accounts")
def api_accounts():
    accs = load_accounts()
    arr = []
    for i, a in enumerate(accs, start=1):
        arr.append({
            "no": i,
            "label": a.get("label") or f"account_{i}",
            "ig_user_id": a.get("ig_user_id", ""),
            "page_id": a.get("page_id", "")
        })
    return jsonify(arr)

# -------------------- 素材一覧 --------------------
@app.get("/api/materials")
def api_materials():
    order = []
    if ORDERS_JSON.exists():
        try: order = json.loads(ORDERS_JSON.read_text("utf-8"))
        except Exception: order = []

    overrides = {}
    if OVERRIDES_JSON.exists():
        try: overrides = json.loads(OVERRIDES_JSON.read_text("utf-8"))
        except Exception: overrides = {}

    files = [p.name for p in OVERLAY_DIR.iterdir() if p.is_file()]
    ordered = [n for n in order if n in files] + [n for n in files if n not in order] if order else sorted(files)

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
    if not fs: return "no files", 400
    for f in fs:
        (OVERLAY_DIR / f.filename).write_bytes(f.read())
    return "ok"

@app.post("/api/remove")
def api_remove():
    data = request.get_json(force=True)
    names = data.get("names") or []
    overrides = {}
    if OVERRIDES_JSON.exists():
        try: overrides = json.loads(OVERRIDES_JSON.read_text("utf-8"))
        except: overrides = {}
    for n in names:
        try: (OVERLAY_DIR / n).unlink(missing_ok=True)
        except: pass
        overrides.pop(n, None)
    OVERRIDES_JSON.write_text(json.dumps(overrides, ensure_ascii=False, indent=2), "utf-8")
    return "ok"

# -------------------- 並び順/テキスト --------------------
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
    if text: overrides[name] = text
    else: overrides.pop(name, None)
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

        mats = json.loads(api_materials().get_data())
        if selected_names:
            mats = [m for m in mats if m["name"] in selected_names]
        if not mats:
            return jsonify({"message": "素材がありません"}), 400

        overrides = {}
        if OVERRIDES_JSON.exists():
            try: overrides = json.loads(OVERRIDES_JSON.read_text("utf-8"))
            except: overrides = {}

        accounts = load_accounts()
        if not accounts:
            return jsonify({"message": "アカウントがありません（accounts.json か igpub.ACCOUNTS を用意）"}), 400

        if all_accounts:
            account_nos = list(range(1, len(accounts)+1))
        else:
            account_nos = [account_no]

        pcr = PosterCoreReel()
        results = []

        for acc_no in account_nos:
            # 背景: background{no}.mp4 -> フォールバック background1.mp4
            bg = BG_DIR / f"background{acc_no}.mp4"
            if not bg.exists():
                fb = BG_DIR / "background1.mp4"
                if fb.exists(): bg = fb
                else:
                    return jsonify({"message": f"背景が見つかりません: {bg.name}"}), 400

            for m in mats:
                overlay = OVERLAY_DIR / m["name"]
                text = (overrides.get(m["name"]) or "").strip() or get_random_text()
                media_id = pcr.post_reel(
                    account_no=acc_no,
                    overlay_path=overlay,
                    background_path=bg,
                    custom_overlay_text=text or None,
                    share_to_feed=False,
                )
                results.append({"account": acc_no, "name": m["name"], "media_id": media_id})

        return jsonify({"message": "投稿完了", "results": results})
    except Exception as e:
        return f"投稿失敗: {e}\n{traceback.format_exc()}", 500

# -------------------- 出力ファイル --------------------
@app.get("/output/<path:name>")
def output_file(name):
    return send_from_directory(OUTPUT_DIR, name)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=True)
