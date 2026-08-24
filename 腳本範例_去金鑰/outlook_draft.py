# -*- coding: utf-8 -*-
r"""
outlook_draft.py — 把 Mandy-Task 中標記「用 Outlook 開草稿」的便利貼，
用你電腦「現場桌面版 Outlook」開成草稿（不是雲端版、也不會自動寄出）。

做法：讀最新備份 JSON → 找 mailOutlook=true 的便利貼 → 用 Outlook COM 開一封草稿視窗
      （mail.Display()，跳出來讓你補收件人再自己寄）→ ledger 記錄避免重複開。

用法：
  試跑不開 Outlook（只列會開哪些）： python outlook_draft.py --dry
  真的開 Outlook 草稿：              python outlook_draft.py
"""
import sys, os, json, glob, hashlib
from pathlib import Path

if sys.stdout is None:
    import io
    sys.stdout = io.StringIO(); sys.stderr = io.StringIO()
else:
    try:
        sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE = Path(__file__).resolve().parent
LEDGER = BASE / "_state" / "drafted_ledger.json"

_HOME = os.path.expanduser("~")
SCAN_DIRS = [
    os.path.join(_HOME, "Downloads"),
    r"你的路徑\任務備份資料夾",
]
NAME_PATTERNS = ["Mandy-Task-自動備份-*.json", "Mandy-Task*.json", "TaskFlow_Backup_*.json", "TaskFlow備份_*.json"]


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


def note_hash(n):
    return hashlib.md5((str(n.get("text", "")) + "|" + str(n.get("tag", ""))).encode("utf-8")).hexdigest()


def make_draft(note):
    """用桌面 Outlook 開一封草稿視窗。回 (ok, msg)。"""
    try:
        import win32com.client
    except ImportError:
        return False, "缺 pywin32：pip install pywin32"
    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)   # 0 = olMailItem
        text = str(note.get("text", "")).strip()          # 任務標題 或 便利貼內容
        detail = str(note.get("note", "")).strip()        # 任務備註（便利貼通常沒有）
        who = str(note.get("assignee", "") or note.get("tag", "") or "").strip()  # 匯報對象/相關人員
        first_line = (text.splitlines()[0] if text else "任務")
        mail.Subject = first_line[:200]

        # 組內文：Dear 稱謂 → 標題 → 備註內容（任務把備註帶進來；便利貼就是 text 本身）
        def esc(s):
            return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
        parts = []   # 每個元素都是「最終 HTML」，最後用 <br> 串起來
        if who and who not in ("All", "none"):
            parts.append("Dear " + esc(who) + ",")   # 依鐵律：Dear 後一律半形逗號
            parts.append("")
        if text:
            parts.append("<b>" + esc(text) + "</b>")   # 標題當重點行
        if detail:
            parts.append("")
            parts.append(esc(detail))
        inner = "<br>".join(parts)
        content_html = "<div style=\"font-family:'Microsoft JhengHei';font-size:12pt;\">" + inner + "</div><br>"

        # 先 Display 讓 Outlook 帶入「預設簽名」到 HTMLBody，再把內容加在簽名上面（保留簽名檔）
        mail.Display(False)
        try:
            sig = mail.HTMLBody or ""
        except Exception:
            sig = ""
        mail.HTMLBody = content_html + sig
        return True, "已開草稿"
    except Exception as e:
        return False, f"Outlook COM 失敗：{e}"


FIREBASE_KEY = r"你的路徑\firebase-key.json（自己的 firebase-admin 服務金鑰）"
FIREBASE_UID = "你的FirebaseUID_在網頁左下角看得到"


def load_cloud():
    try:
        if not os.path.exists(FIREBASE_KEY):
            return None
        import firebase_admin
        from firebase_admin import credentials, firestore
        if not firebase_admin._apps:
            firebase_admin.initialize_app(credentials.Certificate(FIREBASE_KEY))
        d = firestore.client().document(f"users/{FIREBASE_UID}/state/main").get().to_dict() or {}
        return (d.get("notes", []) or [], d.get("tasks", []) or [])
    except Exception as e:
        print(f"[雲端] 直讀失敗，改用備份：{e}"); return None


def main():
    dry = "--dry" in sys.argv
    cloud = load_cloud()
    if cloud is not None:
        notes, tasks = cloud
        print("[來源] 雲端即時資料")
    else:
        backup = find_latest_backup()
        if not backup:
            print("[錯誤] 找不到雲端也找不到備份 JSON。"); sys.exit(2)
        print(f"[來源] 備份檔 {backup}")
        data = json.loads(Path(backup).read_text(encoding="utf-8"))
        notes = data.get("notes", []) if isinstance(data, dict) else []
        tasks = data.get("tasks", []) if isinstance(data, dict) else []
    # 便利貼 + 任務，只要標了 mailOutlook 都開草稿
    flagged = [n for n in notes if isinstance(n, dict) and n.get("mailOutlook")] + \
              [t for t in tasks if isinstance(t, dict) and t.get("mailOutlook")]
    print(f"[標記寄 Outlook] 便利貼+任務共 {len(flagged)} 則")

    if not flagged:
        print("沒有標記「用 Outlook 開草稿」的便利貼或任務。點信封圖示標記後再跑。")
        return

    led = load_ledger()
    opened, skipped, failed = 0, 0, 0
    for n in flagged:
        nid = str(n.get("id"))
        preview = str(n.get("text", "")).replace("\n", " ")[:30]
        h = note_hash(n)
        if led.get(nid) == h:
            print(f"  ○ 內容未變、先前已開過，略過：{preview}"); skipped += 1
            continue
        if dry:
            print(f"  + 會開 Outlook 草稿：{preview}"); opened += 1
            continue
        ok, msg = make_draft(n)
        if ok:
            print(f"  ✔ {msg}：{preview}"); led[nid] = h; opened += 1
        else:
            print(f"  x 失敗：{preview} → {msg}"); failed += 1

    if not dry:
        save_ledger(led)
    print(f"\n[結果] 開草稿 {opened}、略過 {skipped}、失敗 {failed}" + ("（試跑，未實際開）" if dry else ""))
    print("提醒：草稿只會跳出視窗，不會自動寄出；補上收件人後由你自己按寄出。")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
