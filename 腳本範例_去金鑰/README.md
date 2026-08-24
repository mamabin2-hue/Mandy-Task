# 本機背景自動化腳本（去金鑰範例）

這三支是跑在使用者電腦上的 Python 腳本（Windows 排程），**非網站的一部分**。
這裡是「**去金鑰版**」供理解與重建；真正運作的版本在使用者本機、含金鑰、不上傳。
用 `firebase-admin` 直接讀寫 Firestore（免綁卡）。

## 檔案
- `jira_sync.py` — Jira 雙向同步（Task↔Jira）。詳見主 README 第 5 章。
- `line_reminder.py` — 每日到期提醒推 LINE。
- `outlook_draft.py` — 把標記的任務/便利貼用桌面 Outlook 開成草稿。
- `jira_config.範例.txt` — Jira 設定檔範本（複製成 `_state/jira_config.txt` 再填）。

## 要真的跑起來，需自備（都不在此 repo）
- **Firebase service account 金鑰**（firebase-admin 用的 `firebase-key.json`）— 從 Firebase 專案設定下載。
- **你的 Firebase UID**（網頁登入後左下角「我的同步 ID」）。
- **Jira**：API Token + 登入 Email + 網域 + 專案代號 → 填進 `jira_config.txt`。
- **LINE**：Channel Access Token + 你的 User ID → 放進 `line_config.txt`（兩行 `TOKEN=` / `USER_ID=`）。
- **Outlook**：本機安裝 Outlook + `pip install pywin32`。
- 套件：`pip install firebase-admin requests pywin32`

## 執行方式
以 Windows 工作排程器用 `pythonw`（隱形、不跳黑窗）定時執行；
Outlook 草稿因需開視窗必須在使用者桌面 session 執行，其餘可背景執行。

程式碼裡凡是「你的路徑\…」「你的FirebaseUID…」都要換成你自己的值。
