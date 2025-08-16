from __future__ import annotations
import os, json
from pathlib import Path
from typing import Any, Dict, List
from flask import Flask, jsonify, request, render_template_string

app = Flask(__name__, static_folder="static", static_url_path="/static")

BASE = Path(__file__).parent.resolve()
ACCOUNTS_JSON = BASE / "accounts.json"

# ========= accounts.json I/O（新スキーマ: {default_account_no:int, accounts:[...] }） =========
def _ensure_accounts_file() -> None:
    if not ACCOUNTS_JSON.exists():
        ACCOUNTS_JSON.write_text(json.dumps({"default_account_no": 1, "accounts": []}, ensure_ascii=False, indent=2), encoding="utf-8")

def _read_raw() -> Dict[str, Any]:
    _ensure_accounts_file()
    try:
        raw = json.loads(ACCOUNTS_JSON.read_text(encoding="utf-8"))
        if isinstance(raw, list):  # 古い形式の互換（配列だけ）
            raw = {"default_account_no": 1, "accounts": raw}
        raw.setdefault("default_account_no", 1)
        raw.setdefault("accounts", [])
        return raw
    except Exception:
        return {"default_account_no": 1, "accounts": []}

def _write_raw(raw: Dict[str, Any]) -> None:
    ACCOUNTS_JSON.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

def load_accounts() -> Dict[str, Any]:
    return _read_raw()

def upsert_account(item: Dict[str, Any]) -> Dict[str, Any]:
    raw = _read_raw()
    accts: List[Dict[str, Any]] = raw["accounts"]
    no = item.get("no")
    if no is None:
        return raw
    # 既存検索
    idx = next((i for i, a in enumerate(accts) if a.get("no") == no), None)
    if idx is None:
        # 足りないキーを補完しつつ追加。既存キーはそのまま保存できるようゆるくマージ
        base = {
            "no": no,
            "label": item.get("label") or f"account_{no}",
            "ig_user_id": item.get("ig_user_id", ""),
            "page_id": item.get("page_id", ""),
            "access_token": item.get("access_token", ""),
            "last_refresh_ts": item.get("last_refresh_ts", 0.0),
            "expires_in": item.get("expires_in", 0)
        }
        # 余剰キーが来てもマージ
        for k, v in item.items():
            base[k] = v
        accts.append(base)
    else:
        merged = dict(accts[idx])
        for k, v in item.items():
            merged[k] = v
        accts[idx] = merged

    # default の自動設定（新規時など）
    if not raw.get("default_account_no"):
        raw["default_account_no"] = no
    _write_raw(raw)
    return raw

def delete_account(no: int) -> Dict[str, Any]:
    raw = _read_raw()
    accts: List[Dict[str, Any]] = raw["accounts"]
    accts = [a for a in accts if a.get("no") != no]
    raw["accounts"] = accts
    if raw.get("default_account_no") == no:
        raw["default_account_no"] = accts[0]["no"] if accts else 1
    _write_raw(raw)
    return raw

# ========= API =========
@app.get("/api/accounts")
def api_list_accounts():
    """{ default_account_no, accounts } を返す"""
    return jsonify(load_accounts())

@app.post("/api/accounts")
def api_upsert_account():
    try:
        item = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"error": "invalid json"}), 400
    return jsonify(upsert_account(item))

@app.delete("/api/accounts/<int:no>")
def api_delete_account(no: int):
    return jsonify(delete_account(no))

# 将来の投稿 API の枠（今はモックで 200 を返す）
@app.post("/api/post")
def api_post_mock():
    j = request.get_json(force=True) or {}
    return jsonify({"ok": True, "received": j})

# ========= UI（元の並び／ヘッダに各操作ボタン常時表示） =========
INDEX_HTML = """
<!doctype html>
<html lang="ja"><head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>投稿ツール</title>
<style>
  body { font-family: system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, "Noto Sans JP", "Hiragino Kaku Gothic ProN", "Yu Gothic", sans-serif; margin:16px; }
  .bar { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
  .row{ margin-top:12px; }
  select, input, button { height:32px; padding:0 8px; }
  .primary{ background:#1677ff; color:#fff; border:none; }
  .danger { background:#d9363e; color:#fff; border:none; }
  .ghost  { background:#fff; border:1px solid #ddd; }
  .muted{ color:#666; font-size:12px; }
  label { display:inline-flex; gap:6px; align-items:center; }
</style>
</head><body>
  <div class="bar">
    <button id="btn-add" class="ghost">＋追加/更新</button>
    <button id="btn-token-refresh" class="ghost">トークン更新</button>
    <button id="btn-token-check" class="ghost">トークン有効期限チェック</button>
    <button id="btn-del" class="danger">🗑 削除</button>

    <span style="margin-left:16px;">アカウント選択</span>
    <select id="sel-accounts" style="min-width:380px;"></select>

    <label style="margin-left:16px;">IGユーザーID <input id="ig-user-id" style="width:220px;" /></label>
    <label>ページID <input id="page-id" style="width:180px;" /></label>

    <button id="btn-reload" class="ghost">🔄 更新</button>
    <button id="btn-exec" class="primary">🤖 投稿実行</button>
  </div>

  <div class="row muted" id="hint">accounts.json（UTF-8）: {"default_account_no": 1, "accounts": [...]}</div>
  <div class="row" id="status">待機中</div>

<script>
const $ = (s)=>document.querySelector(s);
const statusBox = $("#status");
let state = { default_account_no: 1, accounts: [] };

function setStatus(t){ statusBox.textContent = t; }

function findAccount(no){
  return state.accounts.find(a => String(a.no) === String(no));
}

function populateInputsFromSelected(){
  const no = $("#sel-accounts").value;
  const a = findAccount(no);
  $("#ig-user-id").value = a?.ig_user_id || "";
  $("#page-id").value = a?.page_id || "";
}

async function loadAccounts(){
  try{
    const r = await fetch("/api/accounts");
    state = await r.json();
  }catch(e){ state = { default_account_no: 1, accounts: [] }; }
  const sel = $("#sel-accounts");
  sel.innerHTML = "";
  if(!Array.isArray(state.accounts) || state.accounts.length===0){
    const opt=document.createElement("option");
    opt.value=""; opt.textContent="（accounts.json が空/未読）";
    sel.appendChild(opt);
    setStatus("アカウントがありません。");
    $("#ig-user-id").value = "";
    $("#page-id").value = "";
    return;
  }
  for (const a of state.accounts.sort((x,y)=>Number(x.no)-Number(y.no))){
    const opt=document.createElement("option");
    opt.value = a.no;
    const label = a.label || a.name || `no_${a.no}`;
    opt.textContent = `${a.no}. ${label} (IG:${a.ig_user_id || "-"} / Page:${a.page_id || "-"})`;
    sel.appendChild(opt);
  }
  // 既定選択
  const def = String(state.default_account_no || state.accounts[0].no);
  sel.value = def;
  populateInputsFromSelected();
  setStatus(`読み込み: ${state.accounts.length}件 / 既定: ${def}`);
}

$("#sel-accounts").addEventListener("change", populateInputsFromSelected);
$("#btn-reload").addEventListener("click", loadAccounts);

$("#btn-add").addEventListener("click", async ()=>{
  const sel = $("#sel-accounts");
  const no = parseInt(sel.value || "0", 10) || (state.accounts[0]?.no ?? 1);
  const src = findAccount(no) || { no };
  const payload = {
    ...src,
    no,
    label: src.label || src.name || `account_${no}`,
    ig_user_id: $("#ig-user-id").value || "",
    page_id: $("#page-id").value || ""
  };
  const res = await fetch("/api/accounts", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(payload)});
  if(res.ok){ await loadAccounts(); setStatus("保存しました。"); } else { setStatus("保存失敗"); }
});

$("#btn-del").addEventListener("click", async ()=>{
  const no = $("#sel-accounts").value;
  if(!no) return;
  const res = await fetch(`/api/accounts/${no}`, {method:"DELETE"});
  if(res.ok){ await loadAccounts(); setStatus("削除しました。"); } else { setStatus("削除失敗"); }
});

$("#btn-token-refresh").addEventListener("click", ()=>alert("（既存のトークン更新APIに接続してください）"));
$("#btn-token-check").addEventListener("click", ()=>alert("（既存の有効期限チェックAPIに接続してください）"));

$("#btn-exec").addEventListener("click", async ()=>{
  const no = parseInt($("#sel-accounts").value||"0",10);
  if(!no){ alert("アカウントを選択してください"); return; }
  setStatus("投稿実行中…（/api/post にPOST）");
  try{
    const r = await fetch("/api/post", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({account_no:no})});
    const j = await r.json();
    setStatus("結果: "+JSON.stringify(j));
  }catch(e){ setStatus("投稿APIに接続できませんでした。"); }
});

loadAccounts();
</script>
</body></html>
"""

@app.get("/")
def index():
    return render_template_string(INDEX_HTML)

@app.get("/healthz")
def healthz():
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","8000")), debug=True)
