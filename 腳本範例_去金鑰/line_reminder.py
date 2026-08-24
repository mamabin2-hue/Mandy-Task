# -*- coding: utf-8 -*-
r"""
line_reminder.py — Mandy-Task 每日到期提醒（推 LINE）

做法：
  1. 從 SCAN_DIRS 找「最新一份」Mandy-Task / TaskFlow 備份 JSON
  2. 算出未完成任務中「逾期 / 今天到期 / N 天內到期」的清單
  3. 用 LINE Messaging API 推一則彙整訊息給你

沿用你 Outlook 專案現有的 LINE 設定（TOKEN / USER_ID），不用重設。
只讀本機備份 JSON，不需要 Firebase 金鑰。

用法：
  一般執行（會推 LINE）：  python line_reminder.py
  試跑不推（只印出來）：    python line_reminder.py --dry
"""
import sys, os, json, glob, datetime, shutil
from pathlib import Path

# 主控台/排程編碼相容：console 轉 UTF-8（避免 cp950 印 emoji 爆掉）；pythonw 下 stdout 是 None → 導到空槽
if sys.stdout is None:
    import io
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
else:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:
    import requests
except ImportError:
    print("需要 requests 套件：pip install requests")
    sys.exit(1)

# ============ 設定（可自行修改） ============
# LINE 設定檔（沿用 Outlook 專案那份，兩行 TOKEN= / USER_ID=）
LINE_CONFIG = r"你的路徑\line_config.txt（內容兩行 TOKEN=xxx / USER_ID=xxx）"

# 備份歸檔資料夾：跑完後把備份 JSON 從下載資料夾搬到這裡（不再堆在 Downloads）
ARCHIVE_DIR = r"你的路徑\任務備份資料夾"
ARCHIVE_KEEP = 30   # 歸檔資料夾最多保留幾份（超過刪最舊）

# 掃描這些資料夾，找最新的備份 JSON（可增減）
_HOME = os.path.expanduser("~")
SCAN_DIRS = [
    os.path.join(_HOME, "Downloads"),
    ARCHIVE_DIR,
    # 若你的備份是存到 OneDrive，把資料夾加在這裡，例如：
    # os.path.join(_HOME, "OneDrive", "Mandy-Task備份"),
]

# 備份檔名樣式（只匹配真正的備份，不含金鑰檔如 mandy-task-firebase-adminsdk-*.json）
NAME_PATTERNS = [
    "Mandy-Task-自動備份-*.json",
    "TaskFlow_Backup_*.json",
    "TaskFlow備份_*.json",
]

# 直讀雲端（即時，優先於備份檔）：服務金鑰 + 你的同步 ID
FIREBASE_KEY = r"你的路徑\firebase-key.json（自己的 firebase-admin 服務金鑰）"
FIREBASE_UID = "你的FirebaseUID_在網頁左下角看得到"

DUE_WITHIN_DAYS = 3          # 幾天內算「即將到期」
PUSH_WHEN_ALL_CLEAR = True   # 沒有任何到期/逾期時，要不要也推一則「今天沒事」
# ==========================================

PUSH_URL = "https://api.line.me/v2/bot/message/push"


def load_line():
    p = Path(LINE_CONFIG)
    if not p.exists():
        return None, None
    token = user_id = None
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("TOKEN="):
            token = line[len("TOKEN="):].strip()
        elif line.startswith("USER_ID="):
            user_id = line[len("USER_ID="):].strip()
    return token, user_id


def push(text):
    token, user_id = load_line()
    if not token or not user_id:
        return False, "LINE config 缺 TOKEN 或 USER_ID"
    if len(text) > 4900:
        text = text[:4900] + "\n…(訊息截斷)"
    try:
        r = requests.post(
            PUSH_URL,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"to": user_id, "messages": [{"type": "text", "text": text}]},
            timeout=10,
        )
        return (r.status_code == 200), (f"OK" if r.status_code == 200 else f"HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:
        return False, f"例外: {e}"


def find_latest_backup():
    cands = []
    for d in SCAN_DIRS:
        for pat in NAME_PATTERNS:
            cands += glob.glob(os.path.join(d, pat))
    if not cands:
        return None
    return max(cands, key=os.path.getmtime)


def parse_date(s):
    if not s:
        return None
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except Exception:
        return None


def build_message(tasks, notes=None):
    today = datetime.date.today()
    overdue, due_today, soon = [], [], []
    for t in tasks:
        if (t.get("status") or "") == "done":
            continue
        d = parse_date(t.get("deadline"))
        if not d:
            continue
        text = (t.get("text") or "(未命名任務)").strip().replace("\n", " ")
        if len(text) > 40:
            text = text[:40] + "…"
        diff = (d - today).days
        if diff < 0:
            overdue.append((abs(diff), text))
        elif diff == 0:
            due_today.append(text)
        elif diff <= DUE_WITHIN_DAYS:
            soon.append((diff, text))

    # 便利貼提醒：有設「提醒日 remindDate」的便利貼
    note_due = []
    for n in (notes or []):
        if not isinstance(n, dict):
            continue
        d = parse_date(n.get("remindDate"))
        if not d:
            continue
        diff = (d - today).days
        if diff <= DUE_WITHIN_DAYS:   # 逾期、今天、N天內都提醒
            txt = (n.get("text") or "(空白便利貼)").strip().replace("\n", " ")
            if len(txt) > 40:
                txt = txt[:40] + "…"
            note_due.append((diff, txt))
    note_due.sort(key=lambda x: x[0])

    overdue.sort(key=lambda x: -x[0])
    soon.sort(key=lambda x: x[0])

    total = len(overdue) + len(due_today) + len(soon) + len(note_due)
    if total == 0:
        if not PUSH_WHEN_ALL_CLEAR:
            return None
        return (
            "☀️ Mandy-Task 早安提醒\n"
            "……………………………………\n"
            f"今天（{today.strftime('%m/%d')}）沒有到期或逾期的任務，安心工作 👍"
        )

    lines = [
        "🔔 Mandy-Task 每日到期提醒",
        "……………………………………",
        f"今天是 {today.strftime('%Y/%m/%d (%a)')}",
    ]
    if overdue:
        lines.append("")
        lines.append(f"🔴 逾期（{len(overdue)}）")
        for days, text in overdue:
            lines.append(f"　逾期{days}天　{text}")
    if due_today:
        lines.append("")
        lines.append(f"🟠 今天到期（{len(due_today)}）")
        for text in due_today:
            lines.append(f"　{text}")
    if soon:
        lines.append("")
        lines.append(f"🟡 {DUE_WITHIN_DAYS}天內（{len(soon)}）")
        for days, text in soon:
            lines.append(f"　{days}天後　{text}")
    if note_due:
        lines.append("")
        lines.append(f"📝 便利貼提醒（{len(note_due)}）")
        for days, text in note_due:
            when = "逾期" + str(-days) + "天" if days < 0 else ("今天" if days == 0 else str(days) + "天後")
            lines.append(f"　{when}　{text}")
    lines.append("……………………………………")
    lines.append("記得到 Mandy-Task 更新進度 ✅")
    return "\n".join(lines)


def archive_backups():
    """把 Downloads 等處的備份 JSON 搬到 ARCHIVE_DIR（跨磁碟用 shutil.move）；超過 ARCHIVE_KEEP 份刪最舊。"""
    try:
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
    except Exception as e:
        print(f"[歸檔] 無法建立資料夾 {ARCHIVE_DIR}：{e}"); return
    moved = 0
    for d in SCAN_DIRS:
        if os.path.normcase(os.path.abspath(d)) == os.path.normcase(os.path.abspath(ARCHIVE_DIR)):
            continue   # 不搬歸檔夾自己
        for pat in NAME_PATTERNS:
            for src in glob.glob(os.path.join(d, pat)):
                dst = os.path.join(ARCHIVE_DIR, os.path.basename(src))
                try:
                    if os.path.abspath(src) == os.path.abspath(dst):
                        continue
                    if os.path.exists(dst):
                        os.remove(dst)   # 同名（同一天）視為同一份，覆蓋
                    shutil.move(src, dst)
                    moved += 1
                except Exception as e:
                    print(f"[歸檔] 搬移失敗 {src}：{e}")
    try:
        files = []
        for pat in NAME_PATTERNS:
            files += glob.glob(os.path.join(ARCHIVE_DIR, pat))
        files = sorted(set(files), key=os.path.getmtime)
        while len(files) > ARCHIVE_KEEP:
            old = files.pop(0)
            try: os.remove(old)
            except Exception: pass
    except Exception:
        pass
    if moved:
        print(f"[歸檔] 已搬 {moved} 份備份到 {ARCHIVE_DIR}")


def load_from_cloud():
    """直接從 Firestore 讀即時資料，回 (tasks, notes) 或 None。"""
    try:
        if not os.path.exists(FIREBASE_KEY):
            return None
        import firebase_admin
        from firebase_admin import credentials, firestore
        if not firebase_admin._apps:
            firebase_admin.initialize_app(credentials.Certificate(FIREBASE_KEY))
        d = firestore.client().document(f"users/{FIREBASE_UID}/state/main").get().to_dict() or {}
        return (d.get("tasks", []) or [], d.get("notes", []) or [])
    except Exception as e:
        print(f"[雲端] 直讀失敗，改用備份檔：{e}")
        return None


def main():
    dry = "--dry" in sys.argv
    notes = []
    cloud = load_from_cloud()
    if cloud is not None:
        tasks, notes = cloud
        print(f"[來源] 雲端即時資料")
    else:
        backup = find_latest_backup()
        if not backup:
            print("[錯誤] 找不到雲端也找不到備份 JSON。")
            sys.exit(2)
        print(f"[來源] 備份檔 {backup}")
        try:
            data = json.loads(Path(backup).read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[錯誤] 讀取備份失敗：{e}")
            sys.exit(2)
        tasks = data.get("tasks", []) if isinstance(data, dict) else []
        notes = data.get("notes", []) if isinstance(data, dict) else []
    print(f"[任務] 共 {len(tasks)} 筆，[便利貼] {len(notes)} 則")

    if not dry:
        archive_backups()   # 把散在 Downloads 的備份歸檔到 0-task備份

    msg = build_message(tasks, notes)
    if msg is None:
        print("[結果] 今天沒有到期/逾期任務，且設定為不推播 → 不送。")
        return
    print("\n" + "=" * 40 + "\n" + msg + "\n" + "=" * 40)

    if dry:
        print("\n[試跑] --dry 模式，未實際推送 LINE。")
        return

    ok, res = push(msg)
    print(f"\n[推送] {'成功' if ok else '失敗'}：{res}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
