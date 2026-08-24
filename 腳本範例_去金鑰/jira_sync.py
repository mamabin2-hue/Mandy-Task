# -*- coding: utf-8 -*-
r"""
jira_sync.py — 把 Mandy-Task 中勾選「同步到 Jira」的任務，單向建立到你的 Jira。

方向：只有 Mandy-Task → Jira（不會把 Jira 的變更寫回 Mandy-Task）。
做法：讀你電腦最新一份 Mandy-Task / TaskFlow 備份 JSON → 找出 syncToJira=true 的任務
      → 用 Jira REST API 建立 issue → 記在 ledger 避免重複建立。

用法：
  試跑不建立（強烈建議先跑這個看看會建什麼）： python jira_sync.py --dry
  真的建立到 Jira：                              python jira_sync.py

設定：編輯 _state\jira_config.txt（JIRA_SITE / JIRA_EMAIL / JIRA_TOKEN / PROJECT_KEY / ISSUE_TYPE）。
"""
import sys, os, json, glob, base64
from pathlib import Path

# 主控台/排程編碼相容
if sys.stdout is None:
    import io
    sys.stdout = io.StringIO(); sys.stderr = io.StringIO()
else:
    try:
        sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:
    import requests
except ImportError:
    print("需要 requests 套件：pip install requests"); sys.exit(1)

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "_state" / "jira_config.txt"
LEDGER = BASE / "_state" / "synced_ledger.json"   # {taskId: {"jiraKey":..., "hash":...}}

# 掃描這些資料夾找最新備份 JSON（跟 LINE 提醒一致）
_HOME = os.path.expanduser("~")
SCAN_DIRS = [
    os.path.join(_HOME, "Downloads"),
    r"你的路徑\任務備份資料夾",
]
NAME_PATTERNS = ["Mandy-Task-自動備份-*.json", "Mandy-Task*.json", "TaskFlow_Backup_*.json", "TaskFlow備份_*.json"]


def _read_token_fallback():
    """若 jira_config 的 token 沒填，改從專案根目錄 Mandy-Task.txt 讀（取檔中最長的一段當 token）。"""
    import re
    p = BASE.parent / "Mandy-Task.txt"
    try:
        raw = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    cands = re.findall(r"[A-Za-z0-9_\-\.=]{20,}", raw)
    return max(cands, key=len) if cands else None


def load_config():
    cfg = {}
    if CONFIG.exists():
        for line in CONFIG.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    # token 沒填 / 還是佔位字 → 改讀 Mandy-Task.txt
    tk = cfg.get("JIRA_TOKEN", "")
    if not tk or tk.startswith(("貼上", "你的")):
        fb = _read_token_fallback()
        if fb:
            cfg["JIRA_TOKEN"] = fb
            print("[設定] JIRA_TOKEN 由 Mandy-Task.txt 自動讀入")
    return cfg


def find_latest_backup():
    cands = []
    for d in SCAN_DIRS:
        for pat in NAME_PATTERNS:
            cands += glob.glob(os.path.join(d, pat))
    return max(cands, key=os.path.getmtime) if cands else None


def load_ledger():
    try:
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_ledger(led):
    try:
        LEDGER.write_text(json.dumps(led, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[警告] 寫入 ledger 失敗：{e}")


def task_hash(t):
    return json.dumps({"text": t.get("text"), "note": t.get("note"), "deadline": t.get("deadline"),
                       "status": t.get("status"), "subtasks": t.get("subtasks")}, ensure_ascii=False, sort_keys=True)


import re as _re
# 同步標記（來回同步時用來辨識、並避免一直疊加）。全形/半形括號都認。
_MARKER = "（由 Mandy-Task 同步建立）"
_MARKER_RE = _re.compile(r"[（(]\s*由\s*Mandy-Task\s*同步建立\s*[)）]")


def _strip_marker(text):
    """去掉內文裡（可能重複的）同步標記與尾端多餘空行，避免來回同步越疊越長。"""
    if not text:
        return ""
    s = _MARKER_RE.sub("", str(text))
    # 收掉因移除標記留下的連續空行與前後空白
    s = _re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def build_description(t):
    parts = []
    note_clean = _strip_marker(t.get("note"))   # 先清掉舊標記，最後只補一個，避免重複同步時越來越多
    if note_clean:
        parts.append(note_clean)
    subs = t.get("subtasks") or []
    if subs:
        parts.append("")
        parts.append("子任務：")
        for s in subs:
            parts.append(f"[{'x' if s.get('done') else ' '}] {s.get('text','')}")
    parts.append("")
    parts.append(_MARKER)
    return "\n".join(parts)


def create_issue(cfg, t):
    site = cfg.get("JIRA_SITE", "").replace("https://", "").replace("http://", "").strip("/")
    url = f"https://{site}/rest/api/2/issue"
    auth = base64.b64encode(f"{cfg['JIRA_EMAIL']}:{cfg['JIRA_TOKEN']}".encode()).decode()
    r = requests.post(url, headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
                      json={"fields": _issue_fields(cfg, t)}, timeout=15)
    if r.status_code in (200, 201):
        return True, r.json().get("key", "?")
    return False, f"HTTP {r.status_code}: {r.text[:300]}"


def test_connection(cfg):
    """只驗證帳號/token/專案是否可用，不建立任何 issue。"""
    site = cfg.get("JIRA_SITE", "").replace("https://", "").replace("http://", "").strip("/")
    if not site or site.startswith("你的"):
        print("[測試] JIRA_SITE 尚未填。"); return False
    auth = base64.b64encode(f"{cfg.get('JIRA_EMAIL','')}:{cfg.get('JIRA_TOKEN','')}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}
    try:
        r = requests.get(f"https://{site}/rest/api/2/myself", headers=headers, timeout=15)
    except Exception as e:
        print(f"[測試] 連線失敗（網址可能錯）：{e}"); return False
    if r.status_code == 401:
        print("[測試] ✗ 帳號或 API Token 錯誤（HTTP 401）。請確認 JIRA_EMAIL 與 JIRA_TOKEN。"); return False
    if r.status_code != 200:
        print(f"[測試] ✗ 無法登入（HTTP {r.status_code}）：{r.text[:200]}"); return False
    who = r.json().get("displayName") or r.json().get("emailAddress") or "?"
    print(f"[測試] ✔ 登入成功，帳號：{who}")
    pk = cfg.get("PROJECT_KEY", "")
    rp = requests.get(f"https://{site}/rest/api/2/project/{pk}", headers=headers, timeout=15)
    if rp.status_code == 200:
        pj = rp.json()
        print(f"[測試] ✔ 專案 {pk} 存在：{pj.get('name','')}")
        # 列出該專案可用的 issue type，方便確認 ISSUE_TYPE 填對
        try:
            types = [t.get("name") for t in pj.get("issueTypes", [])]
            if types:
                print(f"[測試] 此專案可用的工作項目類型：{', '.join(types)}（你設定的是 {cfg.get('ISSUE_TYPE','Task')}）")
        except Exception:
            pass
        return True
    else:
        print(f"[測試] ✗ 找不到專案 {pk}（HTTP {rp.status_code}）。請確認 PROJECT_KEY。"); return False


# 統一標籤：每張由 Mandy-Task 同步的卡片都貼這個，方便在 Jira 用「一個標籤」跨所有專案找到全部
SYNC_LABEL = "MandyTask"


def _issue_fields(cfg, t, with_project=True):
    fields = {
        "summary": (t.get("text") or "(未命名任務)")[:250],
        "description": build_description(t),
    }
    if with_project:
        fields["project"] = {"key": cfg.get("PROJECT_KEY", "")}
        fields["issuetype"] = {"name": cfg.get("ISSUE_TYPE", "任務")}
        fields["labels"] = [SYNC_LABEL]   # 建立時就貼上統一標籤
    dl = t.get("deadline")
    if dl:
        fields["duedate"] = str(dl)[:10]
    return fields


def update_issue(cfg, key, t):
    """把 Jira 既有 issue 的內容更新成 Mandy-Task 目前的內容（單向覆蓋）；並補上統一標籤（不動既有標籤）。"""
    site = cfg.get("JIRA_SITE", "").replace("https://", "").replace("http://", "").strip("/")
    url = f"https://{site}/rest/api/2/issue/{key}"
    auth = base64.b64encode(f"{cfg['JIRA_EMAIL']}:{cfg['JIRA_TOKEN']}".encode()).decode()
    # 用 update.labels.add 只「新增」標籤，不會覆蓋掉使用者原本貼的（例如 回task）
    payload = {"fields": _issue_fields(cfg, t, with_project=False), "update": {"labels": [{"add": SYNC_LABEL}]}}
    r = requests.put(url, headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
                     json=payload, timeout=15)
    if r.status_code in (200, 204):
        return True, "已更新"
    return False, f"HTTP {r.status_code}: {r.text[:300]}"


def _adf_text(node):
    """把 Jira 的描述(ADF 格式)攤平成純文字；表格：每列 cell 用 Tab 分隔、每列換行。"""
    if node is None:
        return ""
    if isinstance(node, list):
        return "".join(_adf_text(c) for c in node)
    if isinstance(node, dict):
        t = node.get("type")
        if t == "text":
            return node.get("text", "")
        if t == "hardBreak":
            return "\n"
        parts = [_adf_text(c) for c in node.get("content", [])]
        if t == "tableRow":
            return "\t".join(p.strip() for p in parts) + "\n"
        if t in ("paragraph", "heading"):
            return "".join(parts) + "\n"
        return "".join(parts)
    return ""


def _fetch_jira_cards(cfg):
    """抓「標了 PULL_LABEL」的 Jira 卡片（跨全部專案），回 (list, err)。"""
    import urllib.parse
    site = cfg.get("JIRA_SITE", "").replace("https://", "").replace("http://", "").strip("/")
    label = (cfg.get("PULL_LABEL", "回Task") or "回Task").strip() or "回Task"
    auth = base64.b64encode(f"{cfg.get('JIRA_EMAIL','')}:{cfg.get('JIRA_TOKEN','')}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}
    tasks, token = [], None
    while True:
        jql = urllib.parse.quote(f'labels = "{label}" ORDER BY created DESC')   # 跨全部專案，只看標籤
        url = f"https://{site}/rest/api/3/search/jql?jql={jql}&maxResults=100&fields=summary,duedate,status,description"
        if token:
            url += f"&nextPageToken={token}"
        r = requests.get(url, headers=headers, timeout=20)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}: {r.text[:200]}"
        data = r.json()
        for it in data.get("issues", []):
            f = it.get("fields", {})
            st = ((f.get("status") or {}).get("statusCategory") or {}).get("key", "")
            status = "done" if st == "done" else ("in-progress" if st == "indeterminate" else "todo")
            note = _strip_marker(_adf_text(f.get("description")))   # 拉回時濾掉同步標記，備註不被標記污染
            tasks.append({
                "id": "jira_" + it.get("key", ""), "jiraKey": it.get("key", ""),
                "text": f.get("summary", "") or it.get("key", ""), "note": note,
                "deadline": f.get("duedate") or "", "status": status, "category": "", "fromJira": True,
            })
        token = data.get("nextPageToken")
        if data.get("isLast") or not token:
            break
    return tasks, None


def pull_from_jira(cfg):
    tasks, err = _fetch_jira_cards(cfg)
    if err:
        print(f"[拉取] 失敗 {err}"); return False
    out = BASE / "jira_pull.json"
    out.write_text(json.dumps({"tasks": tasks}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[拉取] 已從 Jira 抓 {len(tasks)} 張卡片 → {out}")
    return True


def pull_to_cloud(cfg, dry=False):
    """抓 Jira 卡片 → 直接合併寫進使用者的 Firestore（一鍵完成，不必再回網頁匯入）。"""
    incoming, err = _fetch_jira_cards(cfg)
    if err:
        print(f"[同步] 抓 Jira 失敗：{err}"); return False
    print(f"[同步] 從 Jira 抓到 {len(incoming)} 張標了「{cfg.get('PULL_LABEL','回Task')}」的卡片")
    uid = (cfg.get("FIREBASE_UID", "") or "").strip()
    if not uid or uid.startswith("貼上"):
        print("[同步] 設定檔缺 FIREBASE_UID（你的同步 ID）"); return False
    keyfile = BASE / "_state" / "firebase-key.json"
    if not keyfile.exists():
        print(f"[同步] 找不到金鑰檔：{keyfile}"); return False
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
    except ImportError:
        print("[同步] 缺 firebase-admin：pip install firebase-admin"); return False
    if not firebase_admin._apps:
        firebase_admin.initialize_app(credentials.Certificate(str(keyfile)))
    db = firestore.client()
    ref = db.document(f"users/{uid}/state/main")
    snap = ref.get()
    data = snap.to_dict() if snap.exists else {}
    tasks = data.get("tasks") if isinstance(data.get("tasks"), list) else []
    added = updated = 0
    for it in incoming:
        k = it.get("jiraKey")
        idx = next((i for i, t in enumerate(tasks) if isinstance(t, dict) and t.get("jiraKey") == k), -1)
        if idx >= 0:
            tasks[idx] = {**tasks[idx], "text": it["text"], "deadline": it["deadline"], "status": it["status"], "jiraKey": k, "fromJira": True}; updated += 1
        else:
            tasks.insert(0, it); added += 1
    if added == 0 and updated == 0:
        print("[同步] 沒有需要更新的卡片（Jira 上沒有標「回Task」的，或內容都一樣）。"); return True
    if dry:
        print(f"[同步] 試跑：會新增 {added}、更新 {updated}（未實際寫入）"); return True
    import time
    data["tasks"] = tasks
    data["writeId"] = "cloudpull_" + str(int(time.time()))
    data["updatedAt"] = int(time.time() * 1000)
    ref.set(data)
    print(f"[同步] ✔ 已直接寫進你的雲端：新增 {added}、更新 {updated}。回 Mandy-Task 網頁重新整理就看到！")
    return True


def _open_firestore(cfg):
    import firebase_admin
    from firebase_admin import credentials, firestore
    keyfile = BASE / "_state" / "firebase-key.json"
    if not keyfile.exists():
        return None, None, f"找不到金鑰檔：{keyfile}"
    if not firebase_admin._apps:
        firebase_admin.initialize_app(credentials.Certificate(str(keyfile)))
    uid = (cfg.get("FIREBASE_UID", "") or "").strip()
    if not uid or uid.startswith("貼上"):
        return None, None, "設定檔缺 FIREBASE_UID"
    db = firestore.client()
    return db, db.document(f"users/{uid}/state/main"), None


def push_to_cloud(cfg, dry=False):
    """從雲端讀 syncToJira 的任務 → 建到 Jira（沒卡號才建）→ 回寫卡號到雲端。全自動、免 bat。"""
    db, ref, err = _open_firestore(cfg)
    if err:
        print(f"[推送] {err}"); return False
    snap = ref.get(); data = snap.to_dict() if snap.exists else {}
    tasks = data.get("tasks") if isinstance(data.get("tasks"), list) else []
    flagged = [t for t in tasks if isinstance(t, dict) and t.get("syncToJira")]
    created = 0
    changed = False
    for t in flagged:
        if t.get("jiraKey"):
            continue  # 已有卡號，先不重覆處理（更新走另一機制）
        if dry:
            print(f"  + 會建立到 Jira：{(t.get('text') or '')[:30]}"); created += 1
            continue
        ok, res = create_issue(cfg, t)
        if ok:
            t["jiraKey"] = res; t["fromJira"] = False; created += 1; changed = True
            print(f"  ✔ 已建立 {res}：{(t.get('text') or '')[:30]}")
        else:
            print(f"  x 失敗：{(t.get('text') or '')[:30]} → {res}")
    if created == 0:
        print("[推送] 沒有新的『同步到 Jira』任務要建立。"); return True
    if changed and not dry:
        import time
        data["tasks"] = tasks; data["writeId"] = "cloudpush_" + str(int(time.time())); data["updatedAt"] = int(time.time() * 1000)
        ref.set(data)
        print(f"[推送] ✔ 已建 {created} 張到 Jira，並把卡號寫回你的雲端。")
    return True


CLOUD_LEDGER = BASE / "_state" / "cloud_ledger.json"


def _load_cloud_ledger():
    try:
        d = json.loads(CLOUD_LEDGER.read_text(encoding="utf-8"))
    except Exception:
        d = {}
    d.setdefault("pushed", {})   # {taskId: jiraKey} 已建過的，防重複建
    d.setdefault("pulled", [])   # [jiraKey] 曾拉過的，網頁刪掉不再復活（墓碑）
    d.setdefault("hashes", {})   # {taskId: 內容hash} 用來判斷內容有沒有改，改了才更新 Jira
    return d


def _save_cloud_ledger(d):
    try:
        CLOUD_LEDGER.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[同步] 寫 ledger 失敗：{e}")


def sync_cloud(cfg, dry=False):
    """安全版雙向同步：單一串行、Jira I/O 在交易外、寫入用 transaction 只更新 tasks 欄位。"""
    from firebase_admin import firestore
    db, ref, err = _open_firestore(cfg)
    if err:
        print(f"[同步] {err}"); return False
    led = _load_cloud_ledger()

    # ---- Phase 1：Jira I/O（在交易之外做，交易只碰 Firestore）----
    incoming, ferr = _fetch_jira_cards(cfg)
    if ferr:
        print(f"[同步] 抓 Jira 失敗（略過本輪拉取）：{ferr}"); incoming = None
    else:
        print(f"[同步] Jira 標「{cfg.get('PULL_LABEL','回Task')}」卡片 {len(incoming)} 張")

    # 先讀一次找出「要推去 Jira 且還沒卡號」的任務，逐一建立（建成功立刻記 ledger 防重）
    try:
        snap0 = ref.get(); data0 = snap0.to_dict() if snap0.exists else {}
    except Exception as e:
        print(f"[同步] 讀雲端失敗：{e}"); return False
    tasks0 = data0.get("tasks") if isinstance(data0.get("tasks"), list) else []
    def _thash(t):
        return json.dumps({"text": t.get("text"), "note": t.get("note"), "deadline": t.get("deadline"), "status": t.get("status")}, ensure_ascii=False, sort_keys=True)
    new_keys = {}   # taskId -> jiraKey（本輪要回寫的）
    for t in tasks0:
        if not (isinstance(t, dict) and t.get("syncToJira")):
            continue
        tid = str(t.get("id"))
        existing_key = t.get("jiraKey") or led["pushed"].get(tid)
        if existing_key:
            # 已有卡號：內容改了才更新 Jira（單向、Task 為準）
            if not t.get("jiraKey"):
                new_keys[tid] = existing_key   # 卡號沒回寫成功 → 補寫回
            h = _thash(t)
            if led["hashes"].get(tid) != h:
                if dry:
                    print(f"  ↻ 會更新 {existing_key}：{(t.get('text') or '')[:26]}")
                else:
                    try:
                        ok, res = update_issue(cfg, existing_key, t)
                    except Exception as e:
                        ok, res = False, f"例外:{e}"
                    if ok:
                        led["hashes"][tid] = h; _save_cloud_ledger(led)
                        print(f"  ↻ 已更新 {existing_key}：{(t.get('text') or '')[:26]}")
                    else:
                        print(f"  x 更新失敗 {existing_key}：{res}")
            continue
        if dry:
            print(f"  + 會建立到 Jira：{(t.get('text') or '')[:26]}"); continue
        try:
            ok, res = create_issue(cfg, t)
        except Exception as e:
            ok, res = False, f"例外:{e}"
        if ok:
            new_keys[tid] = res; led["pushed"][tid] = res; led["hashes"][tid] = _thash(t); _save_cloud_ledger(led)   # 立刻記，防重複
            print(f"  ✔ 已建立 {res}：{(t.get('text') or '')[:26]}")
        else:
            print(f"  x 建立失敗：{(t.get('text') or '')[:26]} → {res}")

    if dry:
        print("[同步] 試跑結束（未寫入）。"); return True

    pulled_set = set(led["pulled"])

    # ---- Phase 2：交易（原子、只更新 tasks 欄位，不整份覆寫）----
    @firestore.transactional
    def _txn(transaction):
        s = ref.get(transaction=transaction)
        d = s.to_dict() if s.exists else {}
        tasks = d.get("tasks") if isinstance(d.get("tasks"), list) else []
        changed = False
        # (a) 回寫本輪新建的卡號
        for t in tasks:
            if not isinstance(t, dict):
                continue
            tid = str(t.get("id"))
            if tid in new_keys and not t.get("jiraKey"):
                t["jiraKey"] = new_keys[tid]; t["fromJira"] = False; changed = True
        # (b) 套用 Jira 拉回（更新既有；只有全新且沒拉過的才新增；已拉過但雲端沒有＝被刪→墓碑不復活）
        if incoming is not None:
            for it in incoming:
                k = it.get("jiraKey")
                idx = next((i for i, t in enumerate(tasks) if isinstance(t, dict) and t.get("jiraKey") == k), -1)
                if idx >= 0:
                    cur = tasks[idx]
                    if cur.get("text") != it["text"] or cur.get("deadline") != it["deadline"] or cur.get("status") != it["status"]:
                        tasks[idx] = {**cur, "text": it["text"], "deadline": it["deadline"], "status": it["status"], "jiraKey": k, "fromJira": True}
                        changed = True
                elif k not in pulled_set:
                    tasks.insert(0, {**it, "category": it.get("category") or ""}); changed = True
                # else：曾拉過但雲端已無 → 使用者刪掉了，不再加回
        if not changed:
            return None
        import time
        transaction.update(ref, {"tasks": tasks, "writeId": "cloudsync_" + str(int(time.time())), "updatedAt": int(time.time() * 1000)})
        return len([t for t in tasks if isinstance(t, dict)])

    try:
        total = _txn(db.transaction())
    except Exception as e:
        print(f"[同步] 交易寫入失敗（本輪不改雲端，下輪重試）：{e}"); return False

    # 交易成功才更新墓碑 ledger（把本輪看到的 Jira 卡都記為「已拉過」）
    if incoming is not None:
        for it in incoming:
            if it.get("jiraKey") and it["jiraKey"] not in led["pulled"]:
                led["pulled"].append(it["jiraKey"])
        _save_cloud_ledger(led)

    if total is None:
        print("[同步] 無實質變更，未寫入。")
    else:
        print(f"[同步] ✔ 完成，已用交易安全更新你的雲端（僅動 tasks 欄位）。回網頁重新整理即可。")
    return True


def check_request(cfg):
    """看門：讀網頁「現在同步」按鈕寫的請求，有新請求才跑完整同步。給每分鐘排程用。"""
    db, ref, err = _open_firestore(cfg)
    if err:
        print(f"[即時] {err}"); return False
    uid = (cfg.get("FIREBASE_UID", "") or "").strip()
    try:
        creq = db.document(f"users/{uid}/control/syncRequest").get()
        ts = (creq.to_dict() or {}).get("ts") if creq.exists else None
    except Exception as e:
        print(f"[即時] 讀請求失敗：{e}"); return False
    led = _load_cloud_ledger()
    if ts and str(ts) != str(led.get("lastReq")):
        print("[即時] 偵測到「現在同步」請求 → 立刻同步")
        ok = sync_cloud(cfg)
        if ok:
            led = _load_cloud_ledger(); led["lastReq"] = ts; _save_cloud_ledger(led)
        else:
            print("[即時] 同步失敗，保留這次請求，下一輪(1 分鐘後)自動重試")
    else:
        print("[即時] 無新請求")
    return True


def main():
    dry = "--dry" in sys.argv
    cfg = load_config()
    if "--checkrequest" in sys.argv:
        ok = check_request(cfg)
        sys.exit(0 if ok else 1)
    if "--synccloud" in sys.argv:
        ok = sync_cloud(cfg, dry=dry)
        sys.exit(0 if ok else 1)
    if "--pushcloud" in sys.argv:
        ok = push_to_cloud(cfg, dry=dry)
        sys.exit(0 if ok else 1)
    if "--test" in sys.argv:
        ok = test_connection(cfg)
        sys.exit(0 if ok else 1)
    if "--pull" in sys.argv:
        ok = pull_from_jira(cfg)
        sys.exit(0 if ok else 1)
    if "--pullcloud" in sys.argv:
        ok = pull_to_cloud(cfg, dry=dry)
        sys.exit(0 if ok else 1)
    missing = [k for k in ("JIRA_SITE", "JIRA_EMAIL", "JIRA_TOKEN", "PROJECT_KEY") if not cfg.get(k) or cfg[k].startswith(("你的", "貼上", "你的公司"))]
    if missing and not dry:
        print(f"[錯誤] 設定檔尚未填好：{', '.join(missing)} → 請編輯 {CONFIG}")
        sys.exit(2)

    backup = find_latest_backup()
    if not backup:
        print("[錯誤] 找不到備份 JSON，請先到 Mandy-Task 網頁下載一次備份。"); sys.exit(2)
    print(f"[來源] {backup}")
    data = json.loads(Path(backup).read_text(encoding="utf-8"))
    tasks = data.get("tasks", []) if isinstance(data, dict) else []
    flagged = [t for t in tasks if t.get("syncToJira")]
    print(f"[任務] 共 {len(tasks)} 筆，勾選同步 {len(flagged)} 筆")

    if not flagged:
        print("沒有勾選『同步到 Jira』的任務。到任務卡片勾選後再跑一次。")
        return

    led = load_ledger()
    created, updated, skipped, failed = 0, 0, 0, 0
    for t in flagged:
        tid = str(t.get("id"))
        text = (t.get("text") or "(未命名)").replace("\n", " ")[:50]
        rec = led.get(tid)
        h = task_hash(t)
        if rec and rec.get("jiraKey"):
            if rec.get("hash") == h:
                print(f"  ○ 已同步、無變更，略過：{text}（{rec['jiraKey']}）"); skipped += 1
                continue
            # 內容有變更 → 單向更新 Jira 卡片內容
            if dry:
                print(f"  ↻ 會更新 {rec['jiraKey']}：{text}"); updated += 1
                continue
            ok, res = update_issue(cfg, rec["jiraKey"], t)
            if ok:
                print(f"  ↻ 已更新 {rec['jiraKey']}：{text}")
                led[tid]["hash"] = h; updated += 1
            else:
                print(f"  x 更新失敗 {rec['jiraKey']}：{text} → {res}"); failed += 1
            continue
        if dry:
            print(f"  + 會建立到 Jira[{cfg.get('PROJECT_KEY','?')}]：{text}" + (f"（截止 {str(t.get('deadline'))[:10]}）" if t.get('deadline') else "")); created += 1
            continue
        ok, res = create_issue(cfg, t)
        if ok:
            print(f"  ✔ 已建立 {res}：{text}")
            led[tid] = {"jiraKey": res, "hash": h}; created += 1
        else:
            print(f"  x 失敗：{text} → {res}"); failed += 1

    if not dry:
        save_ledger(led)
    print(f"\n[結果] 新建 {created}、已存在 {updated}、略過 {skipped}、失敗 {failed}" + ("（試跑，未實際建立）" if dry else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
