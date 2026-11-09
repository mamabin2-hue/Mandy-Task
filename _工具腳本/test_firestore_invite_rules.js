// Firestore 規則測試（只打本機模擬器，不連正式專案）。
// 邀請碼用明顯的測試字串，不是正式環境的碼。
//
// 執行（在 repo 根目錄，需已安裝 firebase、@firebase/rules-unit-testing、firebase-tools）：
//   npx firebase-tools emulators:exec --only firestore --project demo-mandy-invite "node _工具腳本/test_firestore_invite_rules.js"
const fs = require('fs');
const path = require('path');
const {
  initializeTestEnvironment,
  assertFails,
  assertSucceeds
} = require('@firebase/rules-unit-testing');
const {
  doc, getDoc, setDoc, updateDoc, deleteDoc, collection, getDocs, query, where
} = require('firebase/firestore');

const ACTIVE = 'rules-test-active';
const INACTIVE = 'rules-test-off';
const STRING_ACTIVE = 'rules-test-string';

if (!process.env.FIRESTORE_EMULATOR_HOST) {
  console.error('拒絕執行：沒有 FIRESTORE_EMULATOR_HOST。這個測試不能連正式 Firebase。');
  process.exit(1);
}
if ((process.env.GCLOUD_PROJECT || '').indexOf('demo-') !== 0) {
  console.error('拒絕執行：專案 ID 必須以 demo- 開頭，目前是 ' + (process.env.GCLOUD_PROJECT || '(空)'));
  process.exit(1);
}

const root = path.join(__dirname, '..');
let failed = 0;

async function check(name, fn) {
  try {
    await fn();
    console.log('  ok  ' + name);
  } catch (e) {
    failed += 1;
    console.log('  FAIL ' + name);
    console.log('       ' + (e && e.stack ? e.stack.split('\n').slice(0, 4).join('\n       ') : e));
  }
}

function dbOf(env, uid) {
  const ctx = uid ? env.authenticatedContext(uid) : env.unauthenticatedContext();
  return ctx.firestore();
}

async function seed(env) {
  await env.clearFirestore();
  await env.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    await setDoc(doc(db, 'invites', ACTIVE), { active: true });
    await setDoc(doc(db, 'invites', INACTIVE), { active: false });
    await setDoc(doc(db, 'invites', STRING_ACTIVE), { active: 'true' });
    await setDoc(doc(db, 'users', 'legacy-user', 'state', 'main'), { tasks: [{ id: 't1' }], writeId: 'seed' });
  });
}

function profile(code) {
  return { inviteCode: code, createdAt: Date.now() };
}

async function main() {
  const env = await initializeTestEnvironment({
    projectId: 'demo-mandy-invite',
    firestore: {
      rules: fs.readFileSync(path.join(root, 'firestore.rules'), 'utf8')
    }
  });
  try {
    await seed(env);

    const anon = dbOf(env);
    const alice = dbOf(env, 'alice');
    const legacy = dbOf(env, 'legacy-user');

    await check('未登入可 get 已知的有效邀請碼', async () => {
      const snap = await assertSucceeds(getDoc(doc(anon, 'invites', ACTIVE)));
      if (!snap.exists() || snap.data().active !== true) throw new Error('讀到的內容不對');
    });
    await check('未登入 get 不存在的碼不會被規則拒絕（給網頁顯示碼錯誤）', async () => {
      const snap = await assertSucceeds(getDoc(doc(anon, 'invites', 'rules-test-missing')));
      if (snap.exists()) throw new Error('不該存在');
    });
    await check('未登入不能 list 邀請碼', async () => {
      await assertFails(getDocs(collection(anon, 'invites')));
    });
    await check('登入也不能 list，也不能用 active 欄位把碼掃出來', async () => {
      await assertFails(getDocs(collection(alice, 'invites')));
      await assertFails(getDocs(query(collection(alice, 'invites'), where('active', '==', true))));
    });
    await check('客戶端不能新增、修改、刪除邀請碼', async () => {
      await assertFails(setDoc(doc(alice, 'invites', 'rules-test-new'), { active: true }));
      await assertFails(updateDoc(doc(alice, 'invites', ACTIVE), { active: false }));
      await assertFails(deleteDoc(doc(alice, 'invites', ACTIVE)));
    });

    await check('沒有個人檔也沒有舊資料時，不能讀寫 state', async () => {
      await assertFails(getDoc(doc(alice, 'users', 'alice', 'state', 'main')));
      await assertFails(setDoc(doc(alice, 'users', 'alice', 'state', 'main'), { tasks: [] }));
    });
    await check('不能替別人建立個人檔', async () => {
      await assertFails(setDoc(doc(alice, 'users', 'bob'), profile(ACTIVE)));
    });
    await check('不存在的碼不能建立個人檔', async () => {
      await assertFails(setDoc(doc(alice, 'users', 'alice'), profile('rules-test-missing')));
    });
    await check('active 不是布林 true 的碼不能建立個人檔', async () => {
      await assertFails(setDoc(doc(alice, 'users', 'alice'), profile(INACTIVE)));
      await assertFails(setDoc(doc(dbOf(env, 'alice-string'), 'users', 'alice-string'), profile(STRING_ACTIVE)));
    });
    await check('多寫欄位、少欄位、或碼裡帶斜線，都不能建立個人檔', async () => {
      await assertFails(setDoc(doc(alice, 'users', 'alice'), { inviteCode: ACTIVE, createdAt: Date.now(), extra: 1 }));
      await assertFails(setDoc(doc(alice, 'users', 'alice'), { inviteCode: ACTIVE }));
      await assertFails(setDoc(doc(alice, 'users', 'alice'), { inviteCode: 'a/b', createdAt: Date.now() }));
    });
    await check('有效碼可以建立自己的個人檔', async () => {
      await assertSucceeds(setDoc(doc(alice, 'users', 'alice'), profile(ACTIVE)));
    });
    await check('個人檔之後不能改、不能刪', async () => {
      await assertFails(updateDoc(doc(alice, 'users', 'alice'), { inviteCode: INACTIVE }));
      await assertFails(deleteDoc(doc(alice, 'users', 'alice')));
    });
    await check('別人與未登入不能讀這份個人檔', async () => {
      await assertFails(getDoc(doc(dbOf(env, 'bob'), 'users', 'alice')));
      await assertFails(getDoc(doc(anon, 'users', 'alice')));
    });
    await check('有個人檔之後可以讀寫自己的 state、備份與同步請求', async () => {
      const before = await assertSucceeds(getDoc(doc(alice, 'users', 'alice', 'state', 'main')));
      if (before.exists()) throw new Error('新帳號不該先有舊資料');
      await assertSucceeds(setDoc(doc(alice, 'users', 'alice', 'state', 'main'), { tasks: [], writeId: 'n1' }));
      await assertSucceeds(getDoc(doc(alice, 'users', 'alice', 'state', 'main')));
      await assertSucceeds(setDoc(doc(alice, 'users', 'alice', 'backups', 'b1'), { ts: 1 }));
      await assertSucceeds(setDoc(doc(alice, 'users', 'alice', 'backups_meta', 'index'), { list: [] }));
      await assertSucceeds(setDoc(doc(alice, 'users', 'alice', 'control', 'syncRequest'), { ts: 1 }));
    });
    await check('不能讀別人的 state', async () => {
      await assertFails(getDoc(doc(alice, 'users', 'legacy-user', 'state', 'main')));
    });

    await check('舊帳號沒有個人檔也能讀寫自己的 state（不用重填邀請碼）', async () => {
      const snap = await assertSucceeds(getDoc(doc(legacy, 'users', 'legacy-user', 'state', 'main')));
      if (!snap.exists()) throw new Error('舊資料應該還在');
      await assertSucceeds(setDoc(doc(legacy, 'users', 'legacy-user', 'state', 'main'), { tasks: [{ id: 't1' }, { id: 't2' }], writeId: 'u2' }));
      await assertSucceeds(setDoc(doc(legacy, 'users', 'legacy-user', 'backups', 'b9'), { ts: 2 }));
      await assertSucceeds(setDoc(doc(legacy, 'users', 'legacy-user', 'control', 'syncRequest'), { ts: 2 }));
    });
    await check('舊帳號不能讀別人的資料，也不能列出所有使用者', async () => {
      await assertFails(getDoc(doc(legacy, 'users', 'alice', 'state', 'main')));
      await assertFails(getDocs(collection(legacy, 'users')));
      await assertFails(getDocs(collection(anon, 'users')));
    });
  } finally {
    await env.cleanup();
  }
  console.log(failed ? ('\n' + failed + ' 項失敗') : '\n規則測試全部通過');
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
