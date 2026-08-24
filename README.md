# Mandy-Task (TaskFlow) — HR 任務管理系統

單一檔案（`index.html`）的雲端任務管理 Web App，含 Firebase 即時同步。
本 README 讓任何人／AI 讀完就能**完整理解並從零重建**這個系統。

線上版：https://mamabin2-hue.github.io/Mandy-Task/

---

## 1. 這是什麼

給 HR 用的個人任務／筆記管理工具，重點是「簡單、資料不會不見、多裝置即時同步、免綁信用卡」。
整個前端就是**一個 `index.html`**（React 18 + Babel standalone + Tailwind，全部走 CDN，沒有 build step、沒有後端伺服器）。
資料存 Firebase Firestore，靠 Email 登入；每個帳號只看得到自己的資料。

---

## 2. 功能清單（全部實作在 index.html 內）

- **看板模式**：待辦／進行中／自訂欄位（可新增/改名/刪除、拖曳或按鈕排序）；卡片可改狀態、拖曳排序、置頂/置底、一鍵複製內容、標記 Outlook 草稿、歸檔到知識庫。
- **工作台**：今日集中／暫緩／未指定＋**可自訂分區**（新增/改名/刪除、◀▶或拖曳排序）；每欄可直接新增任務；卡片可移分區、移轉中、完成、同欄排序；點任務開完整內容視窗。
- **任務**：子任務(checklist)、備註、貼圖(壓縮到可讀又不撐爆同步)、截止日、計時器、投入歷程補登（每筆可改分鐘/補備註/刪除）、**任務連結 + 狀態連動**、同步到 Jira 勾選。
- **隨手筆記(便利貼)**：顏色、@相關人員、提醒日、貼圖；**可自訂分頁(Sheet)**（新增/改名/刪除/◀▶排序）、便利貼可用下拉或拖到分頁歸類；送匯報清單、標記 Outlook 草稿。
- **每日/週計劃**：待排程池(依類別分欄可搜尋)拖到某天；**有投入時間的任務自動顯示在那天**(綠底「做過N分」)；點小卡開任務內容。
- **任務總表**：Excel 式欄位篩選 + 排序 + 搜尋。
- **找重複**：完全重複/疑似相似分組，**合併絕不丟內容**(備註/圖片/子任務/連結/log/時數全部併保留)，相似組可選保留哪張標題。
- **知識管理**：任務/便利貼歸檔成知識條目(自動建議分類)。
- **統計報表**（內含「CEO 儀表板」分頁）、**已完成頁**(年→月→日/分類/負責人分組)、**回收桶**(便利貼可復原)、**匯報清單**。
- **資料安全**：全域搜尋(任務+便利貼)、雲端即時同步、**每 15 分鐘雲端還原點**(保留最近 24 份，可還原時間點)、每日自動備份下載 JSON、寫入前**驟減防呆**(任務/便利貼數量驟減會先確認，避免誤覆蓋)、保持長期登入。
- **分享/權限**：邀請碼註冊(陌生人無碼不能註冊)、資料各帳號隔離。

---

## 3. 技術架構

- **前端**：單檔 `index.html`。React 18 + ReactDOM + Babel standalone（瀏覽器即時編譯 JSX）＋ Tailwind(CDN)。lucide-react 圖示走 esm.sh，firebase 走 gstatic。無打包、無 node 後端。
- **登入**：Firebase Auth（Email/密碼）。`setPersistence(browserLocalPersistence)` → 長期登入。
- **資料庫**：Firestore。**整份 state 存單一文件** `users/{uid}/state/main`：
  ```
  { tasks, projects, users, notes, catMap, knowledge, deletedNotes, boardColumns, focusZones, noteSheets, writeId, updatedAt }
  ```
  - 讀：`onSnapshot` 訂閱，任何裝置改動即時同步過來。
  - 寫：去抖 800ms `setDoc`。用 `writeId`(自己寫的回音略過) + `hasPendingWrites` + `canWriteRef`(成功讀過才准寫) + `localDirty`(本地正在編輯不被遠端覆蓋) 防衝突。
  - 大小保護：接近 1MB 單文件上限就擋下並提示(貼圖是 base64 存在同文件內)。
- **雲端還原點**：另存 `users/{uid}/backups/{ts}` 快照 + `users/{uid}/backups_meta/index` 小索引，每 15 分鐘一份、留 24 份。
- **主要資料結構**：
  - `task`: `{ id, text, note, status, category, period, deadline, assignee, timeSpent, logs[], subtasks[], images[], zone, linkedIds[], jiraKey, syncToJira, mailOutlook, archived, createdAt, planDate }`
  - `note`: `{ id, text, color, tag, remindDate, images[], sheet, stashed, mailOutlook, createdAt }`
  - `boardColumns/focusZones/noteSheets`: `[{ id, title, builtin }]`

---

## 4. 從零複製部署（重建步驟）

1. **建一個 Firebase 專案**（免費 Spark 方案即可，不用綁卡）：開啟 Authentication(Email/密碼) 與 Firestore Database。
2. **換掉 `index.html` 裡的 `firebaseConfig`**（約在檔案上方 `const firebaseConfig = {...}`）成你自己專案的 Web 設定（apiKey 等；apiKey 是可公開的網頁金鑰，安全由下面的規則 + 登入把關）。
3. **設定 Firestore 安全規則**（每人只能讀寫自己 uid 底下的資料）：
   ```
   rules_version = '2';
   service cloud.firestore {
     match /databases/{database}/documents {
       match /users/{userId}/{document=**} {
         allow read, write: if request.auth != null && request.auth.uid == userId;
       }
     }
   }
   ```
4. **部署**：把 `index.html`(+`.nojekyll`) 放到 GitHub repo，開啟 GitHub Pages（Settings → Pages → 由 main branch 根目錄）。免費 Pages 需 repo 為 **Public**（repo 公開的只是程式碼，使用者資料在 Firebase、靠登入保護，不會外洩）。
5. **邀請碼**：`index.html` 內 `const INVITE_CODE = '...'`。要分享給同事就把網址＋邀請碼給他，他自行註冊，資料各自隔離。

做完就是一個能用的網站，不需要伺服器、不需要付費。

---

## 5. 選用的本機背景自動化（不在本 repo，含金鑰）

以下是**跑在使用者電腦上的 Python 腳本**（Windows 排程），非網站的一部分，因含 API 金鑰而未進 repo；可用 `firebase-admin` 直接讀寫 Firestore（免綁卡）：

- **Jira 雙向同步**：勾「同步到 Jira」的任務 → 建/更新 Jira issue；標籤 `回task` 的 Jira 卡 → 拉回 Task。所有同步卡片打統一標籤 `MandyTask` 便於跨專案搜尋。網頁「⚡現在同步 Jira」寫一個請求文件，本機看門排程約 2 分鐘內處理。
- **LINE 每日到期提醒**：直讀 Firestore，把逾期/今天/N 天內到期的任務與便利貼提醒日 push 到 LINE。
- **Outlook 草稿**：把標記 `mailOutlook` 的任務/便利貼，用桌面 Outlook `win32com` 開成草稿(Display 不自動寄)，內文帶標題+備註、Dear 稱謂(半形逗號)、保留預設簽名。

要重建這部分：需自備 Jira API Token、LINE Channel Token/User ID、Firebase service account 金鑰，並用 Windows 排程以 `pythonw` 隱形執行。

---

## 6. 安全性重點

- **repo 公開 ≠ 資料公開**：公開的是程式碼；使用者的任務/筆記在 Firestore，**每個帳號只能看自己的**(靠 Auth + 上面的規則)，沒有帳號密碼進不去。
- 網頁 `apiKey` 是設計成可公開的（Firebase Web 金鑰），真正把關的是登入 + Firestore 規則。
- 真正的隱私控制 = **邀請碼 / 是否開放註冊**，不是 repo 可見性。

---

## 7. 檔案

- `index.html` — 整個 Web App（唯一必要檔）。
- `.nojekyll` — 讓 GitHub Pages 原樣提供檔案。
- `建置進度.md` / `需求規劃_v1.md` — 開發歷程與需求紀錄。
- `.gitignore` — 排除含金鑰的本機腳本資料夾。
