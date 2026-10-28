# -*- coding: utf-8 -*-
r"""改完 index.html 後的煙霧測試：用隱藏 Edge 開整份頁面，確認 Babel 編譯沒有語法錯誤、畫面有出來（停在登入頁屬正常）。"""
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'index.html')

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    br = p.chromium.launch(channel='msedge', headless=True)
    pg = br.new_page()
    errs = []
    pg.on('console', lambda m: errs.append(m.text) if m.type == 'error' else None)
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto('file:///' + SRC.replace(os.sep, '/'))
    pg.wait_for_timeout(9000)
    body = pg.inner_text('body')
    syn = [e[:160] for e in errs if any(k in e for k in ('SyntaxError', 'Babel', 'Unexpected token'))]
    print('畫面文字：', body[:120].replace('\n', ' '))
    print('語法錯誤：', syn or '無')
    print('其他錯誤（file:// 下 Firebase 連線類屬正常）：', len(errs) - len(syn))
    br.close()
    sys.exit(1 if syn or not body.strip() else 0)
