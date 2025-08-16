from __future__ import annotations

import os
import json
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, request, send_from_directory, render_template_string, Response

# -------------- Flask --------------
app = Flask(__name__, static_folder="static", static_url_path="/static")
BASE = Path(__file__).parent.resolve()

# -------------- パス定義 --------------
ACCOUNTS_JSON = BASE / "accounts.json"        # {default_account_no:int, accounts:[{no,label,ig_user_id,page_id,...}]}
MATERIAL_DIR   = BASE / "static" / "materials"
BG_DIR         = BASE / "static" / "backgrounds"
OUTPUT_DIR     = BASE / "static" / "output"
TEXT_FILE      = BASE / "random_texts.txt"
OVERRIDES_JSON = BASE / "material_overrides.json"   # 素材ごとのコメント保存

for d in [MATERIAL_DIR, BG_DIR, OUTPUT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# -------------- Import guard（落ちないWSGI） --------------
_APP_IMPORT_ERR: Optional[str] = None
try:
    from poster_core_reel import PosterCoreReel
except Exception as e:
    _APP_IMPORT_ERR = "poster_core_reel import failed:\n" + "".join(
        traceback.format_exception(type(e), e, e.__traceback__)
    )
    PosterCoreReel = None  # type: ignore


# =====================================================================
#                               ユーティリティ
# =====================================================================
def _ensure_accounts_file() -> None:
    if not ACCOUNTS_JSON.exists():
        ACCOUNTS_JSON.write_text(
            json.dumps({"default_account_no": 1, "accounts": []}, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

def _read_accounts() -> Dict[str, Any]:
    _ensure_accounts_file()
    try:
        raw = json.loads(ACCOUNTS_JSON.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            raw = {"default_account_no": 1, "accounts": raw}
        raw.setdefault("default_account_no", 1)
        raw.setdefault("accounts", [])
        return raw
    except Exception:
        return {"default_account_no": 1, "accounts": []}

def _write_accounts(raw: Dict[str, Any]) -> None:
    ACCOUNTS_JSON.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

def _load_overrides() -> Dict[str, str]:
    if not OVERRIDES_JSON.exists():
        return {}
    try:
        return json.loads(OVERRIDES_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_overrides(d: Dict[str, str]) -> None:
    OVERRIDES_JSON.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

def _list_materials() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if not MATERIAL_DIR.exists():
        return items
    overrides = _load_overrides()
    for p in sorted(MATERIAL_DIR.iterdir()):
        if not p.is_file():
            continue
        ext = p.suffix.lower().lstrip(".")
        if ext not in {"jpg","jpeg","png","bmp","gif","webp","mp4","mov","m4v","avi","mkv","webm"}:
            continue
        items.append({
            "name": p.name,
            "path": f"/static/materials/{p.name}",
            "ext": ext,
            "comment": overrides.get(p.name, "")
        })
    return items

def _pick_background_for_account(account_no: int) -> Optional[Path]:
    # 優先: background{no}.mp4
    target = BG_DIR / f"background{account_no}.mp4"
    if target.exists():
        return target
    # 代替: backgrounds 内の最初の mp4
    for p in sorted(BG_DIR.glob("*.mp4")):
        return p
    return None

def _font_auto_hint() -> None:
    """フォント環境変数が無ければ、fonts/keiofont.ttf があれば使うように設定"""
    env_key = "REEL_FONT_PATH"
    if os.environ.get(env_key):
        return
    candidate = BASE / "fonts" / "keiofont.ttf"
    if candidate.exists():
        os.environ[env_key] = str(candidate)


# =====================================================================
#                                   API
# =====================================================================

# --- 起動時エラーを見せる ---
if _APP_IMPORT_ERR:
    @app.get("/")
    def _error_root():
        return "アプリ初期化に失敗しました。/__app_error を参照してください。", 500

    @app.get("/__app_error")
    def _app_error():
        return Response(_APP_IMPORT_ERR, mimetype="text/plain", status=500)


# ---------- アカウント ----------
@app.get("/api/accounts")
def api_accounts_get():
    return jsonify(_read_accounts())

@app.post("/api/accounts")
def api_accounts_upsert():
    data = request.get_json(force=True) or {}
    raw = _read_accounts()
    arr: List[Dict[str, Any]] = raw["accounts"]
    no = data.get("no")
    if no is None:
        return jsonify({"error":"no required"}), 400
    idx = next((i for i,a in enumerate(arr) if a.get("no")==no), None)
    if idx is None:
        base = {
            "no": no,
            "label": data.get("label") or f"account_{no}",
            "ig_user_id": data.get("ig_user_id",""),
            "page_id": data.get("page_id",""),
            "access_token": data.get("access_token",""),
            "last_refresh_ts": data.get("last_refresh_ts", 0.0),
            "expires_in": data.get("expires_in", 0)
        }
        for k,v in data.items():
            base[k]=v
        arr.append(base)
        if not raw.get("default_account_no"):
            raw["default_account_no"] = no
    else:
        merged = dict(arr[idx])
        for k,v in data.items():
            merged[k]=v
        arr[idx] = merged
    _write_accounts(raw)
    return jsonify(raw)

@app.delete("/api/accounts/<int:no>")
def api_accounts_delete(no: int):
    raw = _read_accounts()
    arr: List[Dict[str, Any]] = raw["accounts"]
    arr = [a for a in arr if a.get("no") != no]
    raw["accounts"] = arr
    if raw.get("default_account_no") == no:
        raw["default_account_no"] = arr[0]["no"] if arr else 1
    _write_accounts(raw)
    return jsonify(raw)

# ---------- 素材 ----------
@app.get("/api/materials")
def api_materials_list():
    return jsonify(_list_materials())

@app.post("/api/materials/upload")
def api_materials_upload():
    if "files" not in request.files:
        return jsonify({"error":"files field required"}), 400
    files = request.files.getlist("files")
    saved = []
    for f in files:
        filename = f.filename or ""
        if not filename:
            continue
        (MATERIAL_DIR / filename).parent.mkdir(parents=True, exist_ok=True)
        f.save(str(MATERIAL_DIR / filename))
        saved.append(filename)
    return jsonify({"ok": True, "saved": saved})

@app.post("/api/materials/comment")
def api_materials_comment():
    j = request.get_json(force=True) or {}
    name = j.get("name")
    text = j.get("text","").strip()
    if not name:
        return jsonify({"error":"name required"}), 400
    over = _load_overrides()
    if text:
        over[name] = text
    else:
        over.pop(name, None)
    _save_overrides(over)
    return jsonify({"ok": True})

# ---------- ランダムテキスト ----------
@app.get("/api/random_texts")
def api_random_texts_get():
    if not TEXT_FILE.exists():
        return jsonify({"lines":[]})
    try:
        lines = [ln.strip() for ln in TEXT_FILE.read_text(encoding="utf-8").splitlines()]
    except Exception:
        lines = []
    return jsonify({"lines": lines})

@app.post("/api/random_texts")
def api_random_texts_save():
    j = request.get_json(force=True) or {}
    lines = j.get("lines", [])
    if not isinstance(lines, list):
        return jsonify({"error":"lines must be list"}), 400
    TEXT_FILE.write_text("\n".join([str(x) for x in lines]), encoding="utf-8")
    return jsonify({"ok": True})

# ---------- 投稿（ここが“本番”） ----------
@app.post("/api/post")
def api_post():
    if PosterCoreReel is None:
        return jsonify({"error":"PosterCoreReel import failed"}), 500

    j = request.get_json(force=True) or {}
    # パラメータ
    selected_names: List[str] = j.get("materials") or []
    account_no: Optional[int] = j.get("account_no")
    post_all_accounts: bool = bool(j.get("post_all_accounts", False))
    share_to_feed: bool = bool(j.get("share_to_feed", False))

    accounts = _read_accounts()
    acc_list: List[Dict[str, Any]] = accounts.get("accounts", [])
    if not acc_list:
        return jsonify({"error":"no accounts"}), 400

    # 対象素材
    mats = _list_materials()
    if selected_names:
        mats = [m for m in mats if m["name"] in set(selected_names)]
    if not mats:
        return jsonify({"error":"no materials"}), 400

    # 対象アカウント
    target_accounts: List[int] = []
    if post_all_accounts:
        target_accounts = [int(a["no"]) for a in acc_list]
    else:
        if account_no is None:
            # デフォルト
            account_no = int(accounts.get("default_account_no") or acc_list[0]["no"])
        target_accounts = [int(account_no)]

    # フォントの自動ヒント
    _font_auto_hint()

    # 実行
    over = _load_overrides()
    core = PosterCoreReel()
    results: List[Dict[str, Any]] = []

    for acc_no in target_accounts:
        bg = _pick_background_for_account(acc_no)
        if bg is None:
            return jsonify({"error": f"背景動画が見つかりません（static/backgrounds/ に background{acc_no}.mp4 を置くか、少なくとも1本のmp4を置いてください）"}), 400
        for m in mats:
            name = m["name"]
            mat_path = MATERIAL_DIR / name
            if not mat_path.exists():
                results.append({"material": name, "account_no": acc_no, "ok": False, "error": "material not found"})
                continue
            custom_text = over.get(name, "").strip()  # 空ならcore側でrandom_texts.txtから拾う
            try:
                media_id = core.post_reel(
                    account_no=acc_no,
                    overlay_path=mat_path,
                    background_path=bg,
                    custom_overlay_text=custom_text if custom_text else None,
                    share_to_feed=share_to_feed,
                )
                results.append({"material": name, "account_no": acc_no, "ok": True, "media_id": media_id})
            except Exception as e:
                results.append({"material": name, "account_no": acc_no, "ok": False, "error": str(e)})

    return jsonify({"ok": True, "results": results})


# =====================================================================
#                                   UI
# =====================================================================
INDEX_HTML = r"""
<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>動画リール投稿ツール</title>
<style>
  :root { --c:#1677ff; --b:#eee; --t:#444;}
  body { font-family: system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans JP", Arial, sans-serif; margin: 12px; color:var(--t);}
  h1 { font-size:18px; margin:8px 0 12px;}
  .topbar { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
  .btn{ height:32px; padding:0 10px; border:1px solid var(--b); background:#fff; cursor:pointer; }
  .btn.primary{ background:var(--c); color:#fff; border-color:var(--c);}
  .btn.danger{ background:#d9363e; color:#fff; border-color:#d9363e;}
  select,input[type="text"]{ height:32px; padding:0 8px; }
  .tabs{ display:flex; gap:8px; margin-top:12px; }
  .tab{ padding:6px 10px; border-bottom:2px solid transparent; cursor:pointer;}
  .tab.active{ border-color:var(--c); color:var(--c);}
  .panel{ border:1px solid var(--b); padding:10px; margin-top:8px;}
  .grid{ display:grid; grid-template-columns: 240px 1fr; gap:12px; }
  .materials{ display:grid; grid-template-columns: repeat(auto-fill, 120px); gap:10px; align-content:start; }
  .card{ border:1px solid var(--b); border-radius:6px; overflow:hidden; position:relative;}
  .thumb{ width:100%; height:100px; object-fit:cover; background:#f9f9f9;}
  .name{ font-size:12px; padding:4px 6px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .check{ position:absolute; top:6px; left:6px; width:18px; height:18px; }
  .comment{ width:100%; min-height:100px; }
  .stack{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
  .muted{ color:#777; font-size:12px; }
  .row{ margin-top:10px; }
</style>
</head>
<body>
  <h1>動画リール投稿ツール</h1>

  <!-- 常時表示のアクションバー（元UIの位置に合わせる） -->
  <div class="topbar">
    <button class="btn" id="btn-add">＋追加/更新</button>
    <button class="btn" id="btn-del">🗑 削除</button>
    <button class="btn" id="btn-refresh">🔄 再読込</button>
    <span>アカウント:</span>
    <select id="sel-accounts" style="min-width:360px;"></select>
    <label>IGユーザーID <input id="ig-user-id" type="text" style="width:220px;"></label>
    <label>ページID <input id="page-id" type="text" style="width:180px;"></label>
    <label><input type="checkbox" id="chk-all-accounts"> 全アカウントで投稿</label>
    <label><input type="checkbox" id="chk-feed"> フィードにも共有</label>
    <button class="btn primary" id="btn-post">📤 投稿</button>
    <span id="status" class="muted">待機中</span>
  </div>

  <!-- タブ -->
  <div class="tabs">
    <div class="tab active" data-tab="post">投稿</div>
    <div class="tab" data-tab="random">ランダムテキスト</div>
  </div>

  <!-- 投稿パネル -->
  <div class="panel" id="panel-post">
    <div class="grid">
      <!-- 左: 素材 -->
      <div>
        <div class="stack">
          <input type="file" id="file-mats" multiple>
          <button class="btn" id="btn-upload">アップロード</button>
          <span class="muted">素材は iPhone から選択OK。拡張子: 画像/動画</span>
        </div>
        <div class="materials" id="materials"></div>
      </div>
      <!-- 右: コメント（選んだ素材と1:1） -->
      <div>
        <div class="stack"><b>コメント（素材ごと1:1）</b><span class="muted">空ならランダムテキストから自動</span></div>
        <textarea id="comment-box" class="comment" placeholder="選択中の素材用コメント…"></textarea>
        <div class="row stack">
          <button class="btn" id="btn-save-comment">💾 コメント保存</button>
          <span id="sel-name" class="muted">未選択</span>
        </div>
      </div>
    </div>
  </div>

  <!-- ランダムテキスト -->
  <div class="panel" id="panel-random" style="display:none;">
    <div class="stack">
      <button class="btn" id="btn-rand-save">💾 保存</button>
      <span class="muted">1行=1候補。自動保存。</span>
    </div>
    <div class="row">
      <textarea id="rand-box" class="comment" placeholder="例）\n最高すぎる\n今日のいちばん…"></textarea>
    </div>
  </div>

<script>
const $ = s => document.querySelector(s);
const statusBox = $("#status");

let state = { accounts:[], default_account_no:1 };
let materials = []; // {name,path,ext,comment}
let selectedName = null;

// ---------- helpers ----------
function setStatus(t){ statusBox.textContent = t; }

function renderAccounts(){
  const sel = $("#sel-accounts");
  sel.innerHTML = "";
  if(!state.accounts.length){
    const opt=document.createElement("option");
    opt.value=""; opt.textContent="（アカウントなし）";
    sel.appendChild(opt);
    return;
  }
  for(const a of [...state.accounts].sort((x,y)=>Number(x.no)-Number(y.no))){
    const opt=document.createElement("option");
    opt.value = a.no;
    const label = a.label || a.name || `no_${a.no}`;
    opt.textContent = `${a.no}. ${label} (IG:${a.ig_user_id||"-"} / Page:${a.page_id||"-"})`;
    sel.appendChild(opt);
  }
  sel.value = String(state.default_account_no || state.accounts[0].no);
}

function accountSelected(){ return parseInt($("#sel-accounts").value||"0",10)||null; }

function renderMaterials(){
  const wrap = $("#materials");
  wrap.innerHTML = "";
  for(const m of materials){
    const card = document.createElement("div");
    card.className = "card";
    card.dataset.name = m.name;
    const chk = document.createElement("input");
    chk.type="checkbox"; chk.className="check";
    card.appendChild(chk);
    const ext = m.ext.toLowerCase();
    if(["mp4","mov","m4v","avi","mkv","webm"].includes(ext)){
      const v = document.createElement("video");
      v.src = m.path; v.className="thumb"; v.muted=true; v.playsInline=true;
      card.appendChild(v);
    }else{
      const img = document.createElement("img");
      img.src = m.path; img.className="thumb";
      card.appendChild(img);
    }
    const name = document.createElement("div");
    name.className="name"; name.textContent = m.name;
    card.appendChild(name);

    card.addEventListener("click", (e)=>{
      if(e.target===chk) return;
      selectMaterial(m.name);
    });

    wrap.appendChild(card);
  }
}

function selectMaterial(name){
  selectedName = name;
  const m = materials.find(x=>x.name===name);
  $("#sel-name").textContent = name ? `選択中: ${name}` : "未選択";
  $("#comment-box").value = m?.comment || "";
  // カードの選択ハイライトはチェックで代用
}

async function loadAll(){
  setStatus("読み込み中…");
  const [aRes, mRes, rRes] = await Promise.all([
    fetch("/api/accounts"),
    fetch("/api/materials"),
    fetch("/api/random_texts"),
  ]);
  state = await aRes.json();
  materials = await mRes.json();
  const rand = await rRes.json();

  renderAccounts();
  renderMaterials();

  $("#rand-box").value = (rand.lines||[]).join("\n");
  setStatus("準備完了");
}

// ---------- events ----------
$("#btn-refresh").addEventListener("click", loadAll);

$("#btn-add").addEventListener("click", async ()=>{
  const no = accountSelected() || (state.accounts[0]?.no ?? 1);
  const src = state.accounts.find(a=>String(a.no)===String(no)) || {no};
  const payload = {
    ...src,
    no,
    label: src.label || src.name || `account_${no}`,
    ig_user_id: $("#ig-user-id").value || src.ig_user_id || "",
    page_id: $("#page-id").value || src.page_id || "",
  };
  const r = await fetch("/api/accounts", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(payload)});
  if(r.ok){ setStatus("保存しました"); state = await r.json(); renderAccounts(); }
  else setStatus("保存失敗");
});

$("#btn-del").addEventListener("click", async ()=>{
  const no = accountSelected();
  if(!no) return;
  const r = await fetch(`/api/accounts/${no}`, {method:"DELETE"});
  if(r.ok){ setStatus("削除しました"); state = await r.json(); renderAccounts(); }
  else setStatus("削除失敗");
});

$("#sel-accounts").addEventListener("change", ()=>{
  const no = accountSelected();
  const a = state.accounts.find(x=>String(x.no)===String(no));
  $("#ig-user-id").value = a?.ig_user_id || "";
  $("#page-id").value = a?.page_id || "";
});

$("#btn-upload").addEventListener("click", async ()=>{
  const fs = $("#file-mats").files;
  if(!fs || !fs.length){ alert("ファイルを選択してください"); return; }
  const fd = new FormData();
  for(const f of fs) fd.append("files", f, f.name);
  setStatus("アップロード中…");
  const r = await fetch("/api/materials/upload", {method:"POST", body: fd});
  if(r.ok){ await loadAll(); setStatus("アップロード完了"); } else setStatus("アップロード失敗");
});

$("#materials").addEventListener("change", (e)=>{
  // クリックしたカードのチェックON/OFFはそのまま
});

$("#btn-save-comment").addEventListener("click", async ()=>{
  if(!selectedName){ alert("素材を選択してください"); return; }
  const text = $("#comment-box").value;
  const r = await fetch("/api/materials/comment", {method:"POST", headers:{ "Content-Type":"application/json" },
    body: JSON.stringify({name:selectedName, text})
  });
  if(r.ok){
    const m = materials.find(x=>x.name===selectedName);
    if(m) m.comment = text;
    setStatus("コメント保存しました");
  }else setStatus("コメント保存失敗");
});

$("#btn-post").addEventListener("click", async ()=>{
  // 選択チェックの素材を集める（未選択なら全素材）
  const chosen = Array.from(document.querySelectorAll("#materials .card input.check:checked"))
    .map(chk=>chk.parentElement.dataset.name);
  const mats = chosen.length ? chosen : materials.map(m=>m.name);
  if(!mats.length){ alert("素材がありません"); return; }

  const payload = {
    materials: mats,
    account_no: accountSelected(),
    post_all_accounts: $("#chk-all-accounts").checked,
    share_to_feed: $("#chk-feed").checked
  };
  setStatus("投稿実行中…");
  const r = await fetch("/api/post", {method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify(payload)});
  let msg = "";
  try{
    const j = await r.json();
    if(j.ok){
      msg = "投稿完了: " + JSON.stringify(j.results);
    }else{
      msg = "投稿失敗: " + (j.error||"");
    }
  }catch(_){
    msg = "投稿失敗: API応答が不正（JSON以外）";
  }
  setStatus(msg);
  alert(msg);
});

// タブ
for(const el of document.querySelectorAll(".tab")){
  el.addEventListener("click", ()=>{
    document.querySelectorAll(".tab").forEach(t=>t.classList.remove("active"));
    el.classList.add("active");
    const tab = el.dataset.tab;
    $("#panel-post").style.display = tab==="post" ? "" : "none";
    $("#panel-random").style.display = tab==="random" ? "" : "none";
  });
}

// ランダムテキスト保存（都度）
$("#rand-box").addEventListener("input", async ()=>{
  const lines = $("#rand-box").value.split("\n");
  await fetch("/api/random_texts", {method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify({lines})});
});

$("#btn-rand-save").addEventListener("click", async ()=>{
  const lines = $("#rand-box").value.split("\n");
  const r = await fetch("/api/random_texts", {method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify({lines})});
  setStatus(r.ok ? "ランダムテキスト保存" : "保存失敗");
});

// 初期化
loadAll();
</script>
</body>
</html>
"""

@app.get("/")
def index():
    return render_template_string(INDEX_HTML)

@app.get("/healthz")
def healthz():
    return "ok", 200

# 静的: 背景/素材/出力は static/ 以下を直接配信（Flaskのstatic機能でOK）
@app.get("/static/<path:filename>")
def static_files(filename: str):
    return send_from_directory(app.static_folder, filename, conditional=True)


# =====================================================================
#                               エントリ
# =====================================================================
if __name__ == "__main__":
    # 本番Renderではgunicorn起動、ローカルはこれでOK
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","8000")), debug=True)
