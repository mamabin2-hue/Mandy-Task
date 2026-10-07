// 從 index.html 抽出「實際出貨的」分組程式碼來跑，不另外抄一份
const fs = require('fs');
const src = fs.readFileSync(
  'D:/資料/其他/0-0-課程/0-Claude/HR其他工作/Mandy-Task/index.html', 'utf8');

const grab = (re, name) => {
  const m = src.match(re);
  if (!m) { console.log('!! 抽不到：' + name); process.exit(1); }
  return m;
};

// 1) assigneeOf：取 "=" 右邊的箭頭函式當表達式求值（原始碼一字不改）
const assigneeOf = eval(
  '(' + grab(/const assigneeOf = (\(t\) => \{[^\n]*\});/, 'assigneeOf')[1] + ')');

// 2) 分組＋排序：把檔案裡那段原封不動包進函式，const 就留在函式作用域
const groupSrc = grab(
  /const byAssignee = poolGroup === 'assignee';[\s\S]*?const cats = Object\.keys\(groups\)\.sort[^\n]*\n/,
  'grouping')[0];
const run = eval(
  '(function (poolGroup, unplanned, assigneeOf) {\n' + groupSrc +
  '\nreturn { cats: cats, groups: groups, EMPTY: EMPTY };\n})');

const T = [
  { id: 1, text: 'A案', category: '子公司/熊本', assignee: 'Jeff' },
  { id: 2, text: 'B案', category: '子公司/熊本', assignee: 'Dana' },
  { id: 3, text: 'C案', category: '行政/庶務', assignee: 'Jeff' },
  { id: 4, text: 'D案', category: '', assignee: '' },
  { id: 5, text: 'E案', category: '預算', assignee: 'none' },          // none 視為未指定
  { id: 6, text: 'F案', category: '預算', assignee: '- 尚未設定 -' },   // 同上
  { id: 7, text: 'G案', category: '  ', assignee: '  Smark  ' },       // 前後空白要 trim
  { id: 8, text: 'H案' },                                              // 兩個欄位都沒有
  { id: 9, text: 'I案', category: '稽核', assignee: 'Ruby' },
];

let fail = 0;
const eq = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { fail++; console.log('  [錯誤] %s\n      得到 %s\n      預期 %s', label, JSON.stringify(got), JSON.stringify(want)); }
  else console.log('  [OK]   %s', label);
};

console.log('=== assigneeOf（匯報對象正規化）===');
[['Jeff', 'Jeff'], ['', ''], ['none', ''], ['- 尚未設定 -', ''],
 ['  Smark  ', 'Smark'], [undefined, ''], [null, '']].forEach(([inp, want]) => {
  const got = assigneeOf({ assignee: inp });
  const ok = got === want;
  if (!ok) fail++;
  console.log('  ' + (ok ? '[OK]  ' : '[錯誤]') + ' ' + String(JSON.stringify(inp)).padEnd(16) + ' → ' + JSON.stringify(got));
});

console.log('\n=== 依類別分欄 ===');
const byCat = run('category', T, assigneeOf);
eq('欄位順序（未分類排最後）', byCat.cats,
   ['子公司/熊本', '行政/庶務', '預算', '稽核', '未分類']);   // 筆劃序：預13 < 稽17
eq('未分類收了 3 筆（空字串、純空白、沒欄位）',
   byCat.groups['未分類'].map(t => t.text), ['D案', 'G案', 'H案']);

console.log('\n=== 依匯報對象分欄 ===');
const byWho = run('assignee', T, assigneeOf);
eq('欄位順序（未指定排最後）', byWho.cats,
   ['Dana', 'Jeff', 'Ruby', 'Smark', '未指定匯報對象']);
eq('Jeff 有 2 筆', byWho.groups['Jeff'].map(t => t.text), ['A案', 'C案']);
eq('未指定收了 4 筆（空、none、- 尚未設定 -、沒欄位）',
   byWho.groups['未指定匯報對象'].map(t => t.text), ['D案', 'E案', 'F案', 'H案']);
eq('前後空白已 trim → Smark', byWho.groups['Smark'].map(t => t.text), ['G案']);

console.log('\n=== 任務數不可遺漏或重複 ===');
const sum = (g) => Object.values(g).reduce((n, x) => n + x.length, 0);
eq('依類別 合計', sum(byCat.groups), T.length);
eq('依匯報對象 合計', sum(byWho.groups), T.length);

console.log('\n' + '='.repeat(56));
console.log(fail === 0 ? '全部通過（0 失敗）' : '!! 失敗 ' + fail + ' 項');
process.exit(fail ? 1 : 0);
