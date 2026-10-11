import { chromium } from 'playwright';
import { execFileSync, spawn } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const OUT = path.resolve(process.env.PLAN_QA_OUTPUT || '/tmp/yumao-plan-real-e2e');
const repo = path.resolve(fileURLToPath(new URL('..', import.meta.url)), '..');
const frontend = path.join(repo, 'frontend');
const backendPort = Number(process.env.PLAN_QA_BACKEND_PORT || 5518);
const vitePort = Number(process.env.PLAN_QA_VITE_PORT || 5517);
const origin = `http://127.0.0.1:${vitePort}`;
const python = process.env.PLAN_QA_PYTHON || execFileSync('conda', ['run', '-n', 'test', 'python', '-c', 'import sys; print(sys.executable)'], { encoding: 'utf8' }).trim();
await mkdir(OUT, { recursive: false });
const report = { screenshots: [], checks: [], network: [], errors: [], injectedFaults: [] };
let expectedExternalProbe = false;
let dbServer; let vite; let browser; let manifest;
function check(name, passed, evidence = {}) { report.checks.push({ name, status: passed ? 'PASS' : 'FAIL', evidence }); if (!passed) throw new Error(name); }
async function waitForOutput(child, predicate, timeoutMs = 12000) {
  let output = ''; const onData = (chunk) => { output += chunk.toString().replace(/\u001b\[[0-9;]*m/g, ''); };
  child.stdout?.on('data', onData); child.stderr?.on('data', onData);
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline && child.exitCode === null && !predicate(output)) await new Promise((resolve) => setTimeout(resolve, 100));
  child.stdout?.off('data', onData); child.stderr?.off('data', onData);
  if (!predicate(output)) throw new Error(`child process did not become ready: ${output}`);
  return output;
}
async function stopProcess(child) {
  if (!child || child.exitCode !== null) return;
  await new Promise((resolve) => { const timer = setTimeout(() => { if (child.exitCode === null) child.kill('SIGKILL'); resolve(); }, 3000); child.once('exit', () => { clearTimeout(timer); resolve(); }); child.kill('SIGTERM'); });
}
async function createContext(name, width, height) {
  const context = await browser.newContext({ viewport: { width, height }, timezoneId: 'Asia/Shanghai' });
  await context.route('**/*', async (route) => { const url = new URL(route.request().url()); if (url.origin !== origin) { report.network.push({ name, url: url.origin + url.pathname, expected: expectedExternalProbe }); await route.abort('blockedbyclient'); return; } await route.continue(); });
  const page = await context.newPage();
  page.on('pageerror', (error) => report.errors.push({ name, type: 'pageerror', message: error.message }));
  page.on('console', (message) => {
    if (['error', 'warning'].includes(message.type())) {
      const text = message.text();
      const expected = (name === 'desktop-A' && (text.includes('409 (CONFLICT)') || text.includes('ERR_BLOCKED_BY_CLIENT'))) || (name === 'network-fault' && text.includes('ERR_FAILED'));
      report.errors.push({ name, type: message.type(), message: text, expected });
    }
  });
  return { context, page, name };
}
async function screenshot(item, tag) { const file = path.join(OUT, `${tag}.jpg`); await item.page.screenshot({ path: file, fullPage: true }); report.screenshots.push(file); }
async function viewportScreenshot(item, tag) { const file = path.join(OUT, `${tag}.jpg`); await item.page.screenshot({ path: file, fullPage: false }); report.screenshots.push(file); }
async function login(page, username) { await page.goto(`${origin}/login`); await page.getByLabel('用户名').fill(username); await page.getByLabel('密码').fill('Synthetic-only-password-42'); await page.getByRole('button', { name: '登录', exact: true }).click(); await page.getByRole('link', { name: '预约计划', exact: true }).click(); await page.getByRole('heading', { name: '我的预约计划' }).waitFor(); }
async function verifyStorage() {
  const attempts = JSON.parse(await readFile(path.join(OUT, 'upstream-attempts.json'), 'utf8'));
  const db = JSON.parse(execFileSync(python, ['-c', 'import json,sqlite3,sys; db=sqlite3.connect("file:"+sys.argv[1]+"?mode=ro",uri=True); print(json.dumps({"plans":db.execute("SELECT COUNT(*) FROM booking_plans").fetchone()[0],"revisions":db.execute("SELECT COUNT(*) FROM booking_plan_revisions").fetchone()[0],"owners":[r[0] for r in db.execute("SELECT DISTINCT user_id FROM booking_plans")] }))', manifest.database_path], { encoding: 'utf8' }));
  return { attempts, db };
}
try {
  dbServer = spawn(python, ['-m', 'backend.tests.plan_browser_server', '--output', OUT, '--origin', origin, '--port', String(backendPort)], { cwd: repo, stdio: ['ignore', 'pipe', 'pipe'] });
  const serverOutput = await waitForOutput(dbServer, (output) => output.includes('"origin"'));
  manifest = JSON.parse(serverOutput.trim().split('\n').find((line) => line.includes('"origin"')));
  vite = spawn(process.execPath, [path.join(frontend, 'node_modules/vite/bin/vite.js'), '--config', 'e2e/plans-real.vite.config.mjs'], { cwd: frontend, env: { ...Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith('VITE_'))), PLAN_QA_BACKEND: `http://127.0.0.1:${backendPort}`, PLAN_QA_PORT: String(vitePort), PLAN_QA_CACHE: path.join(OUT, 'vite-cache') }, stdio: ['ignore', 'pipe', 'pipe'] });
  await waitForOutput(vite, (output) => output.includes(`http://127.0.0.1:${vitePort}`));
  browser = await chromium.launch({ headless: true });
  const a = await createContext('desktop-A', 1440, 900); await login(a.page, 'plan_user_a'); await a.page.getByText('还没有预约计划').waitFor({ state: 'visible', timeoutMs: 10000 }); check('A starts empty', await a.page.getByText('还没有预约计划').count() === 1);
  expectedExternalProbe = true;
  await a.page.evaluate(() => fetch('https://blocked.synthetic.invalid/should-be-blocked').catch(() => null));
  expectedExternalProbe = false;
  check('browser external request is blocked', report.network.some((item) => item.expected));
  let submittedIntent;
  a.page.on('request', (request) => {
    if (request.url().includes('/api/plans') && request.method() === 'POST' && request.postData()) {
      try { submittedIntent = JSON.parse(request.postData()).intent; } catch { /* the API contract test will report a missing intent */ }
    }
  });
  await a.page.getByRole('button', { name: '新建预约计划' }).click();
  await a.page.getByLabel('目标预约日期').fill('2026-10-20');
  await a.page.getByLabel('预约时长').selectOption('60');
  await a.page.getByLabel('场馆名称或描述（人工偏好）').fill('Playwright真实人工场馆');
  await a.page.getByLabel('场地偏好（人工输入，每行一项）').fill('6号场优先\n5号场备选');
  await a.page.getByLabel(/价格上限/).fill('29.90');
  await a.page.getByLabel('愿意考虑同场馆其他场地（意愿尚未核验）').check();
  await a.page.getByLabel('允许开始时间在指定范围内浮动').check();
  await a.page.getByLabel('最早开始时间').fill('17:00');
  await a.page.getByLabel('最晚开始时间').fill('19:00');
  await a.page.getByTestId('grid-load').click();
  await a.page.getByTestId('grid-cell-0-1').click();
  await a.page.getByTestId('grid-cell-1-1').click();
  await a.page.getByTestId('grid-add-backup-0').click();
  await a.page.getByTestId('grid-promote-backup-0').click();
  check('grid picks one primary and an explicitly ordered backup', await a.page.getByText('首选场地：6号场').count() === 1 && await a.page.getByText('备选 1：5号场').count() === 1);
  await a.page.getByTestId('grid-apply').click();
  check('grid apply remains an unsaved local form change', await a.page.getByText('还没有预约计划').count() === 1 && await a.page.getByTestId('grid-apply-confirmation').count() === 1);
  check('strict mode previews removal of extra fallback', await a.page.getByTestId('grid-proposed-fallback').innerText().then((value) => value.includes('不允许额外场地或时间浮动')));
  await a.page.getByTestId('grid-apply-confirmation').scrollIntoViewIfNeeded();
  await viewportScreenshot(a, 'desktop-grid-review-viewport');
  await screenshot(a, 'desktop-grid-review');
  await a.page.getByTestId('confirm-grid-selection').click();
  check('confirm retains the exact price ceiling', await a.page.getByLabel(/价格上限/).inputValue() === '29.90');
  check('confirm removes unapproved fallback', !(await a.page.getByLabel('愿意考虑同场馆其他场地（意愿尚未核验）').isChecked()) && !(await a.page.getByLabel('允许开始时间在指定范围内浮动').isChecked()));
  await a.page.getByTestId('save-plan').click();
  await a.page.getByText(/已保存预约意向 · 版本 1/).waitFor({ state: 'visible', timeoutMs: 10000 });
  check('A creates', true);
  check('distant date visible', await a.page.getByText('当前不可查询').count() >= 1);
  check('PlanService receives semantic fields only', submittedIntent?.preferred_start_times?.[0] === '17:00' && submittedIntent?.duration_minutes === 60 && submittedIntent?.court_preferences?.join('|') === '6号场优先|5号场备选' && submittedIntent?.fallback_policy?.allow_any_court_in_venue === false && submittedIntent?.price_ceiling_minor === 2990 && !Object.hasOwn(submittedIntent || {}, 'coordinatesList'));
  await screenshot(a, 'desktop-created');
  await a.page.reload(); await a.page.getByRole('heading', { name: 'Playwright真实人工场馆', exact: true }).waitFor({ state: 'visible', timeoutMs: 10000 }); check('refresh persists', true); await a.page.getByRole('button', { name: '编辑计划' }).click(); await a.page.getByLabel('场馆名称或描述（人工偏好）').fill('Playwright编辑后场馆'); await a.page.getByRole('button', { name: '保存预约意向' }).click(); await a.page.getByText(/已保存预约意向 · 版本 2/).waitFor({ state: 'visible', timeoutMs: 10000 }); check('A version increments', true); await a.page.getByRole('button', { name: '版本历史' }).click(); await a.page.getByRole('heading', { name: '版本历史' }).waitFor({ state: 'visible' });
  const revisionsBeforeHistoryPreview=(await verifyStorage()).db.revisions;
  const syntheticHistoryResponse={success:true,message:'synthetic success',resultData:{stepnumber:'2',nodeList:[{nodeid:'synthetic-history-node-a',sitename:'合成历史场地甲'},{nodeid:'synthetic-history-node-b',sitename:'合成历史场地乙'}],timeList:[{time:'18:00',status:'1'},{time:'18:30',status:'0'}],conflictList:['1-0','1-0-3','0-1-3','1-1-7'],priceList:[{x:'0',y:'1',price:'synthetic-history-price'}]}};
  await a.page.locator('input[data-testid="history-response-file"]').setInputFiles({name:'synthetic-history-response.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(syntheticHistoryResponse))});
  await a.page.getByTestId('historical-booking-grid').waitFor({state:'visible',timeoutMs:10000});
  check('history preview marks conflicting duplicate unknown',await a.page.getByText('未知状态').count()>=1&&await a.page.getByText(/历史客户端显示活动占用/).count()>=1);
  check('history preview creates no revision',(await verifyStorage()).db.revisions===revisionsBeforeHistoryPreview);
  await a.page.getByTestId('historical-booking-grid').scrollIntoViewIfNeeded(); await viewportScreenshot(a,'desktop-history-preview-viewport'); await screenshot(a,'desktop-history-preview');
  await a.page.getByRole('heading', { name: '版本历史' }).scrollIntoViewIfNeeded(); await viewportScreenshot(a, 'desktop-history-viewport'); await screenshot(a, 'desktop-history'); check('history visible', true);
  const stale = await createContext('stale-A', 1024, 768); await login(stale.page, 'plan_user_a'); await stale.page.getByRole('button', { name: '编辑计划' }).click(); await stale.page.getByLabel('场馆名称或描述（人工偏好）').fill('并发窗口已保存'); await stale.page.getByRole('button', { name: '保存预约意向' }).click(); await stale.page.getByText(/已保存预约意向 · 版本 3/).waitFor({ state: 'visible', timeoutMs: 10000 }); await a.page.getByRole('button', { name: '关闭历史' }).click(); await a.page.getByRole('button', { name: '编辑计划' }).click(); await a.page.getByLabel('场馆名称或描述（人工偏好）').fill('我的未保存内容'); await a.page.getByRole('button', { name: '保存预约意向' }).click(); await a.page.getByText('版本冲突：计划已被其他窗口更新。你的未保存内容仍保留。').waitFor({ state: 'visible' }); check('409 keeps unsaved draft', await a.page.getByLabel('场馆名称或描述（人工偏好）').inputValue() === '我的未保存内容'); await stale.context.close();
  const network = await createContext('network-fault', 1024, 768); await login(network.page, 'plan_user_b'); await network.context.route('**/api/plans', async (route) => { if (route.request().method() === 'POST') { report.injectedFaults.push('POST /api/plans network abort'); await route.abort('failed'); return; } await route.continue(); }); await network.page.getByRole('button', { name: '新建预约计划' }).click(); await network.page.getByLabel('场馆名称或描述（人工偏好）').fill('网络故障后仍保留'); await network.page.getByLabel('场地偏好（人工输入，每行一项）').fill('任意场地'); await network.page.getByRole('button', { name: '保存预约意向' }).click(); await network.page.getByText('保存结果尚未确认。请读取计划列表或最新版本核对，再决定是否重新保存。').waitFor({ state: 'visible' }); check('network fault keeps draft', await network.page.getByLabel('场馆名称或描述（人工偏好）').inputValue() === '网络故障后仍保留'); await network.context.close();
  const phone = await createContext('phone-B', 390, 844); await login(phone.page, 'plan_user_b'); check('B cannot see A plan', await phone.page.getByText('Playwright编辑后场馆').count() === 0); check('phone no horizontal overflow', await phone.page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)); await screenshot(phone, 'phone-empty'); await phone.page.getByRole('button', { name: '新建预约计划' }).click(); await phone.page.getByLabel('目标预约日期').fill('2026-10-20'); await phone.page.getByLabel('预约时长').selectOption('60'); await phone.page.getByLabel('场馆名称或描述（人工偏好）').fill('手机网格意向'); await phone.page.getByLabel('场地偏好（人工输入，每行一项）').fill('6号场\n5号场'); await phone.page.getByTestId('grid-load').click(); await phone.page.getByTestId('grid-cell-0-0').click(); await phone.page.getByTestId('grid-cell-1-0').click(); await phone.page.getByTestId('grid-add-backup-1').click(); check('phone grid selection is operable', await phone.page.getByText('首选场地：6号场').count() === 1 && await phone.page.getByText('备选 1：5号场').count() === 1); check('phone grid avoids page overflow', await phone.page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)); await phone.page.getByTestId('grid-court-order').scrollIntoViewIfNeeded(); await viewportScreenshot(phone, 'phone-grid-viewport'); await screenshot(phone, 'phone-grid'); const narrow = await createContext('narrow-320', 320, 700); await login(narrow.page, 'plan_user_b'); check('320px no horizontal overflow', await narrow.page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth));
  const verification = await verifyStorage(); check('upstream attempts remain zero', verification.attempts.http_attempts === 0 && verification.attempts.external_socket_attempts === 0, verification.attempts); check('SQLite persisted immutable revisions', verification.db.plans === 1 && verification.db.revisions === 3 && verification.db.owners.length === 1, verification.db);
  await a.context.close(); await phone.context.close(); await narrow.context.close();
} finally { if (browser) await browser.close(); await stopProcess(vite); await stopProcess(dbServer); await writeFile(path.join(OUT, 'results.json'), JSON.stringify(report, null, 2)); }
const unexpectedNetwork = report.network.filter((item) => !item.expected);
const unexpectedErrors = report.errors.filter((item) => !item.expected);
if (unexpectedNetwork.length || unexpectedErrors.length || report.checks.some((item) => item.status !== 'PASS')) process.exitCode = 1;
console.log(JSON.stringify({ output: OUT, checks: report.checks.length, passed: report.checks.filter((item) => item.status === 'PASS').length, failed: report.checks.filter((item) => item.status !== 'PASS').length, network: report.network.length, unexpectedNetwork: unexpectedNetwork.length, errors: report.errors.length, unexpectedErrors: unexpectedErrors.length }));
