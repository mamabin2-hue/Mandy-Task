# -*- coding: utf-8 -*-
r"""
outlook_watch.py — 常駐即時監聽：一按信封、資料一上雲端，就「立刻」開 Outlook 草稿。

原理：用 Firestore 即時監聽(on_snapshot) users/{uid}/state/main。
      背景執行緒偵測到變動 → 通知主執行緒 → 主執行緒用桌面 Outlook 開草稿(COM 要在主執行緒)。
      靠 outlook_draft.py 的既有函式(make_draft / ledger / note_hash)，已開過的略過、不重複。

用法：pythonw outlook_watch.py   （設成登入時自動啟動、常駐；pythonw 無黑窗）
"""
import sys, time, threading

# pythonw 下 stdout 是 None → 導到空槽，避免 print 爆掉
if sys.stdout is None:
    import io
    sys.stdout = io.StringIO(); sys.stderr = io.StringIO()
else:
    try:
        sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import outlook_draft as od   # 重用 make_draft / load_ledger / save_ledger / note_hash / FIREBASE_KEY / FIREBASE_UID

_signal = threading.Event()   # 背景監聽偵測到變動 → set；主執行緒處理完 → clear


def _on_snapshot(doc_snapshot, changes, read_time):
    _signal.set()


def _process_once(ref):
    """讀最新資料，把標記 mailOutlook 且尚未開過的任務/便利貼開成草稿。"""
    try:
        d = ref.get().to_dict() or {}
    except Exception:
        return
    notes = d.get("notes", []) or []
    tasks = d.get("tasks", []) or []
    flagged = [n for n in notes if isinstance(n, dict) and n.get("mailOutlook")] + \
              [t for t in tasks if isinstance(t, dict) and t.get("mailOutlook")]
    if not flagged:
        return
    led = od.load_ledger()
    changed = False
    for n in flagged:
        nid = str(n.get("id"))
        h = od.note_hash(n)
        if led.get(nid) == h:
            continue   # 內容沒變、先前已開過 → 略過
        ok, _msg = od.make_draft(n)   # win32com 在主執行緒開草稿（Display，不自動寄）
        if ok:
            led[nid] = h; changed = True
    if changed:
        od.save_ledger(led)


def main():
    import firebase_admin
    from firebase_admin import credentials, firestore
    if not firebase_admin._apps:
        firebase_admin.initialize_app(credentials.Certificate(od.FIREBASE_KEY))
    db = firestore.client()
    ref = db.document(f"users/{od.FIREBASE_UID}/state/main")

    watch = None
    def start_watch():
        nonlocal watch
        try:
            watch = ref.on_snapshot(_on_snapshot)   # 背景執行緒即時監聽
        except Exception:
            watch = None

    start_watch()
    _signal.set()   # 啟動時先補處理一次（涵蓋啟動前已標記的）

    idle = 0
    while True:
        fired = _signal.wait(timeout=30)   # 有變動就醒；30 秒沒動也醒一次做保底
        _signal.clear()
        _process_once(ref)
        # 監聽若斷線(網路跳動)→ 重新訂閱
        if not fired:
            idle += 1
            if idle >= 20 and watch is None:   # 約 10 分鐘沒監聽→重掛
                start_watch(); idle = 0
        else:
            idle = 0
        time.sleep(1)   # 稍微節流，避免連續變動狂開


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # 常駐程式不因單次例外整支掛掉；等下次啟動
        time.sleep(5)
