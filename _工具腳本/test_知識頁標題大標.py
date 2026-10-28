# -*- coding: utf-8 -*-
r"""知識管理頁回歸測試：從 index.html 抽出「實際出貨的」KnowledgeBase 元件（原始碼一字不改），
放進最小頁面用隱藏 Edge 渲染，驗證：
  1. 清單卡片：標題字比分類大（大標／子標），分類在標題下方
  2. 編輯頁：標題輸入框字級大於分類輸入框
  3. 搜尋：用標題、分類、內容的關鍵字都找得到
  4. 編輯儲存：改標題後 setKnowledge 收到正確資料
用法：python test_知識頁標題大標.py   → 印 OK／錯誤，截圖存到暫存資料夾
"""
import os
import re
import sys
import tempfile

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), 'index.html')
OUT = os.path.join(tempfile.gettempdir(), 'kb_test')
os.makedirs(OUT, exist_ok=True)

src = open(SRC, encoding='utf-8').read()
m = re.search(r'(    const KnowledgeBase = \(\{ knowledge, setKnowledge \}\) => \{[\s\S]*?\n    \};\n)', src)
if not m:
    print('!! 抽不到 KnowledgeBase'); sys.exit(1)
comp = m.group(1)

HTML = r'''<!doctype html><html><head><meta charset="utf-8">
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://unpkg.com/react@18.2.0/umd/react.development.js"></script>
<script src="https://unpkg.com/react-dom@18.2.0/umd/react-dom.development.js"></script>
<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
<style>body{font-family:"Microsoft JhengHei";background:#f8fafc}</style></head>
<body><div id="root" style="padding:24px;height:900px"></div>
<script type="text/babel">
const Icon = () => <span style={{display:'inline-block',width:14}}>•</span>;
const BookOpen = Icon, FileText = Icon, X = Icon, Plus = Icon, Search = Icon, ChevronDown = Icon, Edit2 = Icon, Trash2 = Icon, Check = Icon;
__COMP__
window.__saved = null;
const App = () => {
  const [k, setK] = React.useState([
    { id: 'a', title: '預算事', category: 'HTUS', content: 'HR估：人力、簽證費', updatedAt: 3 },
    { id: 'b', title: '月會流程', category: '會議/報告', content: '議程與紀錄', updatedAt: 2 },
    { id: 'c', title: '利梭出勤', category: '子公司/利梭', content: '免打卡設定', updatedAt: 1 },
  ]);
  return <KnowledgeBase knowledge={k} setKnowledge={(n) => { window.__saved = n; setK(n); }} />;
};
ReactDOM.createRoot(document.getElementById('root')).render(<App />);
</script></body></html>'''.replace('__COMP__', comp)

page_path = os.path.join(OUT, 'kb.html')
open(page_path, 'w', encoding='utf-8').write(HTML)

fail = 0
def ok(label, cond):
    global fail
    fail += 0 if cond else 1
    print(('  [OK]   ' if cond else '  [錯誤] ') + label)

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    br = p.chromium.launch(channel='msedge', headless=True)
    pg = br.new_page(viewport={'width': 1300, 'height': 950})
    pg.goto('file:///' + page_path.replace('\\', '/'))
    pg.wait_for_selector('h4', timeout=30000)
    pg.screenshot(path=os.path.join(OUT, '1_清單.png'))
    sz = pg.evaluate("""() => { const h = document.querySelector('h4'); const c = h.nextElementSibling;
        return {t: parseFloat(getComputedStyle(h).fontSize), c: c ? parseFloat(getComputedStyle(c).fontSize) : 0,
                ct: c ? c.textContent : '', below: c ? c.getBoundingClientRect().top > h.getBoundingClientRect().top : false}; }""")
    ok(f'卡片：標題 {sz["t"]}px ＞ 分類 {sz["c"]}px，分類「{sz["ct"]}」在標題下方', sz['t'] > sz['c'] > 0 and sz['below'])

    box = pg.locator('input[placeholder="搜尋標題、分類、內容…"]')
    for q, want in (('預算', '預算事'), ('利梭', '利梭出勤'), ('會議/報告', '月會流程'), ('免打卡', '利梭出勤'), ('htus', '預算事')):
        box.fill(q); pg.wait_for_timeout(150)
        got = pg.locator('h4').all_inner_texts()
        ok(f'搜尋「{q}」→ {got}', got == [want])
    box.fill('')

    pg.locator('h4', has_text='預算事').click()
    pg.wait_for_selector('input[title="標題"]')
    pg.screenshot(path=os.path.join(OUT, '2_編輯.png'))
    es = pg.evaluate("""() => ({t: parseFloat(getComputedStyle(document.querySelector('input[title="標題"]')).fontSize),
                                c: parseFloat(getComputedStyle(document.querySelector('input[title="分類"]')).fontSize)})""")
    ok(f'編輯頁：標題 {es["t"]}px ＞ 分類 {es["c"]}px', es['t'] > es['c'])
    pg.locator('input[title="標題"]').fill('預算事（改）')
    pg.get_by_text('儲存').click(); pg.wait_for_timeout(200)
    saved = pg.evaluate('window.__saved')
    ok('儲存後資料正確（標題改、分類與內容不變、共 3 筆）',
       saved and len(saved) == 3 and any(x['title'] == '預算事（改）' and x['category'] == 'HTUS' and x['content'].startswith('HR估') for x in saved))
    br.close()

print('截圖：', OUT)
print('結果：', '全部通過' if fail == 0 else f'{fail} 項失敗')
sys.exit(1 if fail else 0)
