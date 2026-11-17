# -*- coding: utf-8 -*-
r"""便利貼「移到分頁」下拉回歸測試：用實際出貨的 index.html（一字不改），只把 Firebase 換成本機假模組
（自動登入、資料從 window.__DATA 讀、寫入存到 window.__saved），用隱藏 Edge 操作：
  1. 進隨手筆記 → 目前分頁有 3 張便利貼
  2. 第 1 張的分頁下拉選「Jeff」→ 目前分頁剩 2 張、Jeff 分頁有 1 張
  3. 雲端寫入的資料該張 sheet='jeff'
  4. 相關人員選「Jeff」（有同名分頁）→ 自動歸到 Jeff 分頁
  5. 相關人員選「雅芳」（沒有同名分頁）→ 留在原分頁
  6. 新增便利貼時相關人員選 Jeff → 直接進 Jeff 分頁
用法：python test_便利貼移分頁.py
"""
import os, sys, json, tempfile, urllib.parse
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), 'index.html')
OUT = os.path.join(tempfile.gettempdir(), 'note_sheet_test')
os.makedirs(OUT, exist_ok=True)
src = open(SRC, encoding='utf-8').read()

def mod(js):
    return 'data:text/javascript;charset=utf-8,' + urllib.parse.quote(js)

APP = mod("export const initializeApp=()=>({});")
AUTH = mod("""export const getAuth=()=>({currentUser:{uid:'u1',email:'t@test'}});
export const onAuthStateChanged=(a,cb)=>{setTimeout(()=>cb({uid:'u1',email:'t@test'}),0);return()=>{}};
export const signInWithEmailAndPassword=async()=>({});export const createUserWithEmailAndPassword=async()=>({});
export const signOut=async()=>{};export const sendPasswordResetEmail=async()=>{};
export const setPersistence=async()=>{};export const browserLocalPersistence={};""")
FS = mod("""export const getFirestore=()=>({});
export const doc=(db,...p)=>({path:p.join('/')});
const snap=(d)=>({exists:()=>!!d,data:()=>d,metadata:{hasPendingWrites:false}});
export const onSnapshot=(ref,cb)=>{ if(ref.path.endsWith('state/main')) setTimeout(()=>cb(snap(window.__DATA)),50); else setTimeout(()=>cb(snap(null)),50); return()=>{} };
export const setDoc=async(ref,d)=>{ if(ref.path.endsWith('state/main')) window.__saved=d; };
export const getDoc=async()=>snap(null);
export const deleteDoc=async()=>{};""")

page_src = (src.replace('"https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js"', json.dumps(APP))
               .replace('"https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js"', json.dumps(AUTH))
               .replace('"https://www.gstatic.com/firebasejs/10.12.2/firebase-firestore.js"', json.dumps(FS)))
DATA = {
    'tasks': [], 'projects': [], 'users': ['Jeff', '雅芳'], 'knowledge': [], 'deletedNotes': [],
    'notes': [{'id': 'n1', 'text': '蔡顧問的事', 'createdAt': 1}, {'id': 'n2', 'text': '週報', 'createdAt': 2},
              {'id': 'n3', 'text': '週會', 'createdAt': 3}],
    'noteSheets': [{'id': 'active', 'title': '目前', 'builtin': True}, {'id': 'jeff', 'title': 'Jeff'},
                   {'id': 'stashed', 'title': '暫存', 'builtin': True}],
}
page_src = page_src.replace('<body>', '<body><script>window.__DATA=' + json.dumps(DATA, ensure_ascii=False) + ';</script>', 1)
page = os.path.join(OUT, 'notes.html')
open(page, 'w', encoding='utf-8').write(page_src)

fail = 0
def ok(label, cond):
    global fail
    fail += 0 if cond else 1
    print(('  [OK]   ' if cond else '  [錯誤] ') + label)

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    br = p.chromium.launch(channel='msedge', headless=True)
    pg = br.new_page(viewport={'width': 1600, 'height': 1000})
    errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto('file:///' + page.replace('\\', '/'))
    pg.wait_for_selector('text=隨手筆記', timeout=60000)
    pg.wait_for_timeout(1500)
    modal = pg.locator('div.fixed.inset-0')
    if modal.count():
        print('  （開頁彈窗：', modal.first.inner_text()[:120].replace('\n', ' '), '→ 關閉）')
        pg.keyboard.press('Escape'); pg.wait_for_timeout(300)
        if modal.count():
            btns = modal.first.locator('button')
            btns.nth(btns.count() - 1).click(); pg.wait_for_timeout(300)
    pg.locator('text=隨手筆記').first.click()
    pg.wait_for_selector('select[title="移到哪個分頁"]', timeout=20000)
    cnt = lambda: pg.locator('select[title="移到哪個分頁"]').count()
    ok(f'目前分頁 3 張（實際 {cnt()}）', cnt() == 3)
    pg.locator('select[title="移到哪個分頁"]').first.select_option('jeff')
    pg.wait_for_timeout(1500)
    pg.screenshot(path=os.path.join(OUT, 'after_select.png'))
    ok(f'選 Jeff 後目前分頁剩 2 張（實際 {cnt()}）', cnt() == 2)
    pg.locator('button', has_text='Jeff（').first.click()
    pg.wait_for_timeout(500)
    ok(f'Jeff 分頁有 1 張（實際 {cnt()}）', cnt() == 1)
    # 回目前分頁測相關人員
    pg.locator('button', has_text='目前（').first.click(); pg.wait_for_timeout(400)
    tagsel = lambda i: pg.locator('select[title="移到哪個分頁"]').nth(i).locator('xpath=preceding-sibling::select[1]')
    cards = pg.locator('select[title="移到哪個分頁"]')
    tagsel(1).select_option('雅芳'); pg.wait_for_timeout(600)
    ok(f'相關人員選雅芳（沒有同名分頁）→ 目前仍 2 張（實際 {cnt()}）', cnt() == 2)
    tagsel(0).select_option('Jeff'); pg.wait_for_timeout(600)
    ok(f'相關人員選 Jeff → 目前剩 1 張（實際 {cnt()}）', cnt() == 1)
    pg.fill('#newNoteInput', '新的便利貼給 Jeff')
    pg.select_option('#noteUserSelect', 'Jeff')
    pg.locator('button', has_text='貼上便利貼').click(); pg.wait_for_timeout(600)
    ok(f'新增時相關人員選 Jeff → 目前仍 1 張（實際 {cnt()}）', cnt() == 1)
    pg.locator('button', has_text='Jeff（').first.click(); pg.wait_for_timeout(500)
    ok(f'Jeff 分頁共 3 張（實際 {cnt()}）', cnt() == 3)
    pg.screenshot(path=os.path.join(OUT, 'jeff_tab.png'))
    pg.wait_for_timeout(2500)
    saved = pg.evaluate('() => window.__saved && window.__saved.notes')
    sheet = next((n.get('sheet') for n in (saved or []) if n['id'] == 'n1'), None)
    ok(f'寫回雲端的 n1.sheet = {sheet}', sheet == 'jeff')
    ok(f'頁面無 JS 錯誤 {errs[:1]}', not errs)
    br.close()
print('結果：', '全部 OK' if fail == 0 else f'{fail} 項錯誤', '｜截圖', OUT)
sys.exit(1 if fail else 0)
