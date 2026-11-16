# -*- coding: utf-8 -*-
r"""看板欄寬回歸測試：從 index.html 抽出「實際出貨的」前段程式（helpers＋ProjectPicker＋TaskCard，一字不改）
與看板欄位的 className，組成最小頁面用隱藏 Edge 渲染，驗證：
  1. 各欄寬度相同（差 ≤ 2px）
  2. 版面夠寬時欄位平均占滿、不溢出；不夠寬時每欄維持最小 360px（左右捲動）
  3. 卡片內容沒有被撐出欄外（scrollWidth ≤ clientWidth + 1）
用法：python test_看板欄寬平均.py   → 印 OK／錯誤，截圖存到暫存資料夾 board_test
"""
import os, re, sys, tempfile
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), 'index.html')
OUT = os.path.join(tempfile.gettempdir(), 'board_test')
os.makedirs(OUT, exist_ok=True)
src = open(SRC, encoding='utf-8').read()

# 前段：<head>…到 TaskCard.displayName 為止（含 imports、helpers、TaskCard）
cut = src.index("TaskCard.displayName = 'TaskCard';") + len("TaskCard.displayName = 'TaskCard';")
head = src[:cut]
# 看板外層與欄位 className（取實際原始碼）
m_wrap = re.search(r'<div className="([^"]*lg:flex-row[^"]*pb-10)">\s*\{boardColumns\.map\(\(col, idx\)', src)
m_col = re.search(r"<div key=\{col\.id\} className=\{`([^`]*)\$\{style\.bg\}`\}", src)
if not (m_wrap and m_col):
    print('!! 抽不到看板 className'); sys.exit(1)
WRAP, COL = m_wrap.group(1), m_col.group(1)

tail = r'''
    const cols = [{id:'todo',title:'待辦'},{id:'review',title:'待Mandy看'},{id:'in-progress',title:'進行中'},{id:'blocked',title:'卡住'},{id:'done',title:'已完成'}];
    const mk = (id, st, t) => ({ id, status: st, text: t, category: 'AI應用相關作業', timeLogs: [], subtasks: [], assignee: 'Claude', note: '產出：D:\\資料\\其他\\0-0-課程\\0-Claude\\HR其他工作\\0-助理\\20261116_班別設定總表.xlsx ｜另 3 個上班時間待欣榆確認' });
    const tasks = [
      mk('1','todo','宥中-獎懲簽呈'), mk('2','review','【待你決定】班別設定總表：現場 11 位課長／組長用彈性班 a0003，要不要改正常班 a0002'),
      mk('3','in-progress','指揮中心資料夾＋CLAUDE.md（目標／驗收、派工單範本）＋資料來源地圖＋自檢資料新鮮度'),
      mk('4','blocked','短'), mk('5','done','已完成的一件事'),
    ];
    const noop = () => {};
    const App = () => (
      <div style={{padding: 24}}>
        <div id="wrap" className="__WRAP__">
          {cols.map(col => (
            <div key={col.id} data-col={col.id} className={`__COL__bg-slate-50/80 border-slate-200`}>
              <h3 className="text-lg font-black">{col.title}</h3>
              <div className="flex flex-col gap-0 min-h-[200px]">
                {tasks.filter(t => t.status === col.id).map(task => (
                  <TaskCard key={task.id} task={task} projects={DEFAULT_PROJECTS} users={[]} activeTimer={null}
                    updateTask={noop} deleteTask={noop} toggleStatus={noop} toggleTimer={noop} addManualLog={noop}
                    deleteLog={noop} updateLogNote={noop} updateLogStart={noop} updateLogDuration={noop}
                    compact={false} onArchive={noop} boardColumns={cols} moveTaskInColumn={noop} moveTaskToEdge={noop}
                    linkedTasks={[]} onOpenLinkPicker={noop} onJumpTask={noop} onUnlink={noop} statusTitle={col.title} onExpand={noop} />
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
    createRoot(document.getElementById('root')).render(<App />);
  </script>
</body></html>'''.replace('__WRAP__', WRAP).replace('__COL__', COL)
page = os.path.join(OUT, 'board.html')
open(page, 'w', encoding='utf-8').write(head + tail)

fail = 0
def ok(label, cond):
    global fail
    fail += 0 if cond else 1
    print(('  [OK]   ' if cond else '  [錯誤] ') + label)

print('欄位 className：', COL)
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    br = p.chromium.launch(channel='msedge', headless=True)
    for vw in (2560 - 256, 1920 - 256, 1366 - 256):   # 扣掉左側選單寬度
        pg = br.new_page(viewport={'width': vw, 'height': 1000})
        errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.goto('file:///' + page.replace('\\', '/'))
        pg.wait_for_selector('[data-col] h3', timeout=60000)
        pg.wait_for_timeout(1500)
        r = pg.evaluate("""() => { const w = document.getElementById('wrap');
            const cs = [...w.querySelectorAll(':scope > [data-col]')];
            return { wrap: w.clientWidth, cols: cs.map(c => Math.round(c.getBoundingClientRect().width)),
                     right: Math.max(...cs.map(c => c.getBoundingClientRect().right)) - w.getBoundingClientRect().right,
                     spill: cs.filter(c => c.scrollWidth > c.clientWidth + 1).map(c => c.dataset.col) }; }""")
        pg.screenshot(path=os.path.join(OUT, f'board_{vw}.png'), full_page=False)
        print(f'視窗 {vw}px：欄寬 {r["cols"]}，容器 {r["wrap"]}')
        ok(f'  {vw}px 各欄等寬（差 {max(r["cols"]) - min(r["cols"])}px）', max(r['cols']) - min(r['cols']) <= 2)
        need = 5 * 360 + 4 * 24
        if r['wrap'] >= need:
            ok(f'  {vw}px 版面夠寬：欄位占滿且沒有超出（右側超出 {round(r["right"])}px）', r['right'] <= 1)
        else:
            ok(f'  {vw}px 版面不夠寬：每欄維持最小 360px（{min(r["cols"])}px），可左右捲動', min(r['cols']) >= 359)
        ok(f'  {vw}px 卡片沒有撐出欄外 {r["spill"]}', not r['spill'])
        ok(f'  {vw}px 頁面無 JS 錯誤 {errs[:1]}', not errs)
        pg.close()
    br.close()
print('結果：', '全部 OK' if fail == 0 else f'{fail} 項錯誤', '｜截圖', OUT)
sys.exit(1 if fail else 0)
