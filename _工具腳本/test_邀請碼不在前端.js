// 靜態檢查：邀請碼常數不能回到前端或文件，註冊順序必須先問伺服器再建立帳號。
// 不內含任何真實邀請碼。執行：node _工具腳本/test_邀請碼不在前端.js
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
let failed = 0;
const ok = (cond, msg) => {
  if (cond) console.log('  ok  ' + msg);
  else { console.log('  FAIL ' + msg); failed += 1; }
};

const read = (rel) => fs.readFileSync(path.join(root, rel), 'utf8');
const html = read('index.html');
const rules = read('firestore.rules');
const readme = read('README.md');
const progress = read('建置進度.md');

const bannedFiles = ['index.html', 'README.md', '建置進度.md', 'firestore.rules', 'firebase.json', '.firebaserc', '需求規劃_v1.md'];
for (const rel of bannedFiles) {
  const text = read(rel);
  ok(!text.includes('INVITE_CODE'), rel + ' 不含 INVITE_CODE');
}

ok(!/const\s+\w*INVITE\w*\s*=\s*['"]/.test(html), 'index.html 沒有把邀請碼寫成常數');
ok(html.includes('invites'), 'index.html 會讀 invites 集合');
ok(html.includes('function assertInviteActive'), '有伺服器端邀請碼檢查函式');
ok(html.includes('function accountMayEnter'), '舊帳號可不經邀請碼進入');
ok(html.includes('legacyOrInvited') === false, '舊帳號判斷放在規則，不放在網頁');

const regAt = html.indexOf('const code = await assertInviteActive(invite);');
const createAt = html.indexOf('createUserWithEmailAndPassword(fbAuth', regAt);
const profileAt = html.indexOf("setDoc(doc(fbDb, 'users', cred.user.uid)", regAt);
ok(regAt > 0 && createAt > regAt && profileAt > createAt, '註冊順序：先查邀請碼，再建立帳號，再寫個人檔');
ok(html.indexOf('endRegistration()', profileAt) > profileAt, '個人檔寫完才放開登入守門');

const shapeSrc = html.match(/function inviteCodeShapeOk\(code\) \{[\s\S]*?\n    \}/);
ok(!!shapeSrc, '抽得到 inviteCodeShapeOk');
const inviteCodeShapeOk = shapeSrc ? eval('(' + shapeSrc[0] + ')') : () => false;
ok(inviteCodeShapeOk('  rules-test-active  ') === true, '一般測試形狀可通過');
ok(inviteCodeShapeOk('') === false, '空字串拒絕');
ok(inviteCodeShapeOk('   ') === false, '空白拒絕');
ok(inviteCodeShapeOk('a/b') === false, '含斜線拒絕');
ok(inviteCodeShapeOk('.') === false && inviteCodeShapeOk('..') === false, '. 與 .. 拒絕');
ok(inviteCodeShapeOk('x'.repeat(129)) === false, '超過 128 拒絕');
ok(inviteCodeShapeOk('__secret__') === false, '保留文件 ID 拒絕');
ok(inviteCodeShapeOk('ok-碼') === true, '一般字元可通過');

ok(rules.includes('allow get: if true;'), '規則允許 get 單筆邀請碼');
ok(rules.includes('allow list: if false;'), '規則拒絕 list 邀請碼');
ok(rules.includes('allow create, update, delete: if false;'), '客戶端不能寫邀請碼');
ok(rules.includes('exists(') && rules.includes('get('), '註冊用 exists/get 檢查邀請碼');
ok(rules.includes('legacyOrInvited'), '舊帳號有 state/main 即可繼續');
ok(rules.includes('state/main'), '舊資料路徑有寫進規則');
ok(!rules.includes('INVITE_CODE'), '規則檔沒有邀請碼常數');

ok(readme.includes('2026.11.09') && progress.includes('2026.11.09'), 'README 與建置進度都有這次版本號');
ok(progress.includes('回滾'), '建置進度有回滾說明');
ok(readme.includes('firestore.rules'), 'README 指向規則檔');

console.log(failed ? ('\n' + failed + ' 項失敗') : '\n全部通過');
process.exit(failed ? 1 : 0);
