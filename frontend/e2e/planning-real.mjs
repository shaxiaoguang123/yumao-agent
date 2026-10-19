import { chromium } from 'playwright';
import { execFileSync, spawn } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const output = path.resolve(process.env.PLANNING_QA_OUTPUT || '/tmp/yumao-planning-real-e2e');
const repo = path.resolve(fileURLToPath(new URL('../..', import.meta.url)));
const frontend = path.join(repo, 'frontend');
const backendPort = Number(process.env.PLANNING_QA_BACKEND_PORT || 5628);
const vitePort = Number(process.env.PLANNING_QA_VITE_PORT || 5627);
const origin = `http://127.0.0.1:${vitePort}`;
const python = process.env.PLAN_QA_PYTHON || execFileSync('conda', ['run','-n','test','python','-c','import sys;print(sys.executable)'], {encoding:'utf8'}).trim();
await mkdir(output, {recursive:false});
const report = {provider:'Fake Provider; no real supplier tested',checks:[],screenshots:[],externalRequests:[],errors:[]};
let backend, vite, browser, manifest;
function check(name, ok, evidence={}) {report.checks.push({name,ok,evidence});if(!ok)throw new Error(name);}
async function ready(child, marker) {
  let text='';
  const read=chunk=>{text+=chunk.toString().replace(/\u001b\[[0-9;]*m/g,'');};
  child.stdout.on('data',read);child.stderr.on('data',read);
  const deadline=Date.now()+15000;
  while(child.exitCode===null&&!text.includes(marker)&&Date.now()<deadline)await new Promise(resolve=>setTimeout(resolve,100));
  child.stdout.off('data',read);child.stderr.off('data',read);
  if(!text.includes(marker))throw new Error(`isolated server startup failed: ${text}`);
  return text;
}
async function stop(child) {
  if(!child||child.exitCode!==null)return;
  await new Promise(resolve=>{const timer=setTimeout(()=>{if(child.exitCode===null)child.kill('SIGKILL');resolve();},3000);child.once('exit',()=>{clearTimeout(timer);resolve();});child.kill('SIGTERM');});
}
function storage() {
  return JSON.parse(execFileSync(python,['-c',`import json,sqlite3,sys
db=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True)
print(json.dumps({'plans':db.execute('SELECT count(*) FROM booking_plans').fetchone()[0], 'revisions':db.execute('SELECT count(*) FROM booking_plan_revisions').fetchone()[0], 'models':db.execute('SELECT count(*) FROM ai_models').fetchone()[0], 'plaintext_keys':db.execute('SELECT count(*) FROM ai_models WHERE CAST(api_key_ciphertext AS TEXT)=?',('Synthetic-model-key-only-42',)).fetchone()[0]}))`,manifest.database_path],{encoding:'utf8'}));
}
async function context(name,width=1440,height=900) {
  const ctx=await browser.newContext({viewport:{width,height},timezoneId:'Asia/Shanghai'});
  await ctx.route('**/*',async route=>{if(new URL(route.request().url()).origin!==origin){report.externalRequests.push(name);await route.abort('blockedbyclient');}else await route.continue();});
  const page=await ctx.newPage();page.on('pageerror',error=>report.errors.push(error.message));
  return {ctx,page};
}
async function login(page,user) {await page.goto(origin+'/login');await page.getByLabel('用户名').fill(user);await page.getByLabel('密码',{exact:true}).fill('Synthetic-only-password-42');await page.getByRole('button',{name:'登录',exact:true}).click();await page.getByRole('link',{name:'预约计划',exact:true}).click();await page.getByTestId('plan-tab-query').waitFor();await page.getByTestId('plan-tab-agent').click();await page.locator('.agent-credential-gate[data-state="ready"]').waitFor();}
async function screenshot(page,name) {const file=path.join(output,name+'.jpg');await page.screenshot({path:file,fullPage:true});report.screenshots.push(file);}
const description='下周六14-16，1号和4号场，不要一小时，不用候选。';
const replacement='下周六18-20，4号场，不要一小时，不用候选。';
async function generate(page,message) {
  await page.getByTestId('plan-tab-agent').click();
  await page.locator('.agent-credential-gate[data-state="ready"]').waitFor();
  await page.getByTestId('restart-conversation').click();
  await page.getByTestId('proposal-message').fill(message);
  await page.getByTestId('generate-proposal').click();
}
async function waitScope(page) {
  await page.getByTestId('plan-tab-manual').click();
  await page.getByTestId('queue-cell-0-0').waitFor();
  await page.getByTestId('plan-tab-agent').click();
}
try {
  backend=spawn(python,['-m','backend.tests.planning_browser_server','--output',output,'--origin',origin,'--port',String(backendPort)],{cwd:repo,stdio:['ignore','pipe','pipe']});
  manifest=JSON.parse((await ready(backend,'"origin"')).split('\n').find(line=>line.startsWith('{')));
  vite=spawn(process.execPath,[path.join(frontend,'node_modules/vite/bin/vite.js'),'--config','e2e/plans-real.vite.config.mjs'],{cwd:frontend,env:{...Object.fromEntries(Object.entries(process.env).filter(([key])=>!key.startsWith('VITE_'))),PLAN_QA_BACKEND:`http://127.0.0.1:${backendPort}`,PLAN_QA_PORT:String(vitePort),PLAN_QA_CACHE:path.join(output,'vite-cache')},stdio:['ignore','pipe','pipe']});
  await ready(vite,origin);
  browser=await chromium.launch({headless:true});
  const a=await context('A');await login(a.page,'plan_user_a');await waitScope(a.page);
  await generate(a.page,description);await a.page.getByTestId('queue-preview').waitFor();
  await a.page.getByText('队列没有经过模型复核（尚未配置模型）。',{exact:true}).first().waitFor();
  check('missing optional model still previews a scoped queue without saving',storage().plans===0&&await a.page.getByTestId('confirm-save-proposal').isEnabled());

  await generate(a.page,'后天');await a.page.getByTestId('proposal-answer').waitFor();
  const transcriptBeforeReload=await a.page.getByRole('log').innerText();
  await a.page.reload();await a.page.getByTestId('plan-tab-agent').click();
  await a.page.locator('.agent-credential-gate[data-state="ready"]').waitFor();
  await a.page.getByTestId('proposal-answer').waitFor();
  check('active agent conversation and clarification survive a browser refresh',await a.page.getByRole('log').innerText()===transcriptBeforeReload);
  await a.page.getByTestId('restart-conversation').click();await a.page.getByTestId('proposal-message').waitFor();

  await a.page.getByRole('link',{name:'模型设置',exact:true}).click();
  await a.page.getByRole('button',{name:'添加AI模型',exact:true}).click();
  await a.page.getByLabel('显示名称').fill('合成规划模型');await a.page.getByLabel('兼容接口地址').fill('https://model.example/v1');await a.page.getByLabel('模型名称',{exact:false}).fill('synthetic-planner');await a.page.getByLabel(/^API Key/).fill('Synthetic-model-key-only-42');
  await a.page.getByRole('button',{name:'保存模型',exact:true}).click();await a.page.getByText('API Key 已配置（不会显示密钥）',{exact:false}).waitFor();
  check('model config stores encrypted secret without echo',storage().plaintext_keys===0);
  await a.page.getByLabel('当前使用模型').selectOption({label:'合成规划模型 · synthetic-planner'});await a.page.getByLabel('默认模型').selectOption({label:'合成规划模型 · synthetic-planner'});await a.page.getByRole('button',{name:'保存模型选择'}).click();await a.page.getByText('当前模型与默认模型已更新。').waitFor();
  await a.page.getByRole('button',{name:'测试连接',exact:true}).click();await a.page.getByText('模型连接成功。').waitFor();check('explicit connection test reaches the fake provider',true);
  await a.page.getByTestId('test-model-parsing').click();await a.page.getByText('连接正常，追问优先级与队列复核测试通过。测试不会保存预约队列。').waitFor();check('queue capability test never writes a booking plan',storage().plans===0&&storage().revisions===0);
  await a.page.getByRole('button',{name:'添加AI模型',exact:true}).click();await a.page.getByLabel('显示名称').fill('备用合成模型');await a.page.getByLabel('兼容接口地址').fill('https://alternate.example/v1');await a.page.getByLabel('模型名称',{exact:false}).fill('synthetic-alternate');await a.page.getByLabel('认证方式').selectOption('none');await a.page.getByRole('button',{name:'保存模型',exact:true}).click();await a.page.getByRole('heading',{name:'备用合成模型',exact:true}).waitFor();check('multiple model configs persist',storage().models===2);await screenshot(a.page,'models-desktop');

  await a.page.getByRole('link',{name:'预约计划',exact:true}).click();await waitScope(a.page);
  await generate(a.page,'下周六14-16，不要一小时，不用候选。');
  await a.page.getByRole('log').getByText(/2小时要订哪几号场/).waitFor();
  await a.page.getByTestId('proposal-answer').fill('打2小时');await a.page.getByTestId('continue-proposal').click();
  await a.page.getByRole('log').getByText(/2小时要订哪几号场/).last().waitFor();
  check('a duration reply does not invent court 2',await a.page.getByTestId('queue-preview').count()===0&&storage().plans===0);
  await a.page.getByTestId('proposal-answer').fill('1号和4号');await a.page.getByTestId('continue-proposal').click();await a.page.getByTestId('queue-preview').waitFor();
  check('clarification previews two candidates without automatic save',await a.page.locator('[data-testid="queue-entries"] li').count()===2&&storage().plans===0);
  await a.page.getByTestId('proposal-message').fill('改成下周六18-20');
  check('pending original-message edit blocks saving',await a.page.getByTestId('confirm-save-proposal').isDisabled());
  await a.page.getByRole('button',{name:'保留原描述',exact:true}).click();
  await screenshot(a.page,'proposal-desktop');await a.page.getByTestId('confirm-save-proposal').click();await a.page.getByText(/队列已保存/).waitFor();
  check('explicit confirmation writes one queue revision',storage().plans===1&&storage().revisions===1);

  await a.page.reload();await a.page.getByTestId('plan-tab-current').click();await a.page.locator('.ticket-queue-card').waitFor();
  const targetDate=await a.page.locator('.ticket-queue-card .ticket-card-heading > strong').innerText();
  check('reload reads the saved manual queue',await a.page.locator('.ticket-queue-card').count()===1);
  await waitScope(a.page);await generate(a.page,replacement);await a.page.getByTestId('replace-warning').waitFor();
  check('replacing an existing queue requires a preview first',storage().revisions===1);
  await a.page.getByTestId('confirm-save-proposal').click();await a.page.getByText(/队列已保存/).waitFor();check('confirmed replacement appends revision 2',storage().revisions===2);
  await a.page.getByTestId('plan-tab-current').click();await a.page.getByRole('button',{name:`${targetDate}版本历史`,exact:true}).click();await a.page.locator('.queue-history details').nth(1).waitFor();check('both queue revisions remain available',await a.page.locator('.queue-history details').count()===2);await screenshot(a.page,'history-desktop');await a.page.getByRole('button',{name:'关闭历史',exact:true}).click();

  await generate(a.page,description+'模拟失败');await a.page.getByTestId('queue-preview').waitFor();await a.page.getByText('队列没有经过模型复核（模型暂时不可用）。',{exact:true}).first().waitFor();check('optional review failure preserves the deterministic draft without saving',storage().revisions===2);
  await generate(a.page,description);await a.page.getByTestId('queue-preview').waitFor();
  const session=await (await a.ctx.request.get(origin+'/api/auth/session')).json();
  const credentials=await (await a.ctx.request.get(origin+'/api/credentials')).json();const credentialId=credentials.credentials[0].credential_id;
  const current=await (await a.ctx.request.get(`${origin}/api/plans/manual-queues/${targetDate}?credential_id=${encodeURIComponent(credentialId)}`)).json();
  const concurrent=await a.ctx.request.put(`${origin}/api/plans/manual-queues/${targetDate}`,{headers:{Origin:origin,'X-CSRF-Token':session.csrf_token},data:{base_version:current.queue.version,credential_id:credentialId,entries:[{court_preference:'8号场',scope_label:'羽毛球',start_time:'18:00',end_time:'20:00',duration_minutes:120}]}});
  check('concurrent synthetic queue change appends revision 3',concurrent.status()===200&&(await concurrent.json()).queue.version===3);
  await a.page.getByTestId('confirm-save-proposal').click();await a.page.getByText(/这一天的队列刚被改过/).waitFor();check('409 retains draft and blocks stale save',storage().revisions===3&&await a.page.getByTestId('queue-preview').isVisible()&&await a.page.getByTestId('confirm-save-proposal').isDisabled());
  await a.page.getByTestId('regenerate').click();await a.page.getByTestId('queue-preview').waitFor();check('regeneration reads the latest queue version without a write',storage().revisions===3&&await a.page.getByTestId('confirm-save-proposal').isEnabled());await screenshot(a.page,'conflict-desktop');

  await generate(a.page,description+'不要自动付款');await a.page.getByTestId('queue-preview').waitFor();check('default payment authorization adds no extra preview gate',await a.page.getByTestId('confirm-save-proposal').isEnabled()&&storage().revisions===3);
  const b=await context('B');await login(b.page,'plan_user_b');await b.page.getByTestId('plan-tab-current').click();check('B cannot see A queues',await b.page.locator('.ticket-queue-card').count()===0);await b.page.getByRole('link',{name:'设置 · AI模型',exact:true}).click();await b.page.getByText('还没有配置可用模型',{exact:false}).waitFor();check('B cannot see A models',await b.page.getByRole('heading',{name:'合成规划模型',exact:true}).count()===0);await b.page.getByRole('link',{name:'预约计划',exact:true}).click();
  await generate(b.page,'下周六14-16选1号场，18-19选4号场，不用候选。');await b.page.getByTestId('queue-preview').waitFor();
  check('mixed duration slots keep their own courts',await b.page.locator('[data-testid="queue-entries"] li').count()===2&&storage().revisions===3);
  await generate(b.page,'下周六14-16打3小时，1号场，不要一小时，不用候选。');
  await b.page.getByRole('log').getByText(/当天累计时长还是单个时段/).waitFor();
  check('three-hour intent is clarified before any queue can be saved',await b.page.getByTestId('queue-preview').count()===0&&storage().revisions===3);
  await generate(b.page,'下周六14-16选1号场，不要一小时。');
  await b.page.getByRole('log').getByText(/2小时还要再加候选时间/).waitFor();
  await b.page.getByTestId('proposal-answer').fill('再加18-20选4号场');await b.page.getByTestId('continue-proposal').click();
  await b.page.getByRole('log').getByText(/2小时还要再加候选时间/).last().waitFor();
  await b.page.getByTestId('proposal-answer').fill('不用');await b.page.getByTestId('continue-proposal').click();
  await b.page.getByRole('log').getByText(/不能直接交叉组合/).waitFor();
  check('different courts across windows require confirmation before cross-product',await b.page.getByTestId('queue-preview').count()===0&&storage().revisions===3);
  await b.page.getByTestId('proposal-answer').fill('1号和4号');await b.page.getByTestId('continue-proposal').click();await b.page.getByTestId('queue-preview').waitFor();
  check('explicit common-court confirmation unlocks the cross product',await b.page.locator('[data-testid="queue-entries"] li').count()===4&&storage().revisions===3);
  await generate(b.page,'下周六14-16，1号场，不要额外候选。');
  await b.page.getByRole('log').getByText(/还要加1小时的备选吗/).waitFor();
  await b.page.getByTestId('proposal-answer').fill('我要，15-16，不用候选');await b.page.getByTestId('continue-proposal').click();
  await b.page.getByRole('log').getByText(/1小时要订哪几号场/).waitFor();
  check('yes for the one-hour queue is not cancelled by declining more windows',await b.page.getByTestId('queue-preview').count()===0);
  await b.page.getByTestId('proposal-answer').fill('3号场');await b.page.getByTestId('continue-proposal').click();await b.page.getByTestId('queue-preview').waitFor();
  check('the one-hour candidate keeps its independent court',await b.page.locator('[data-testid="queue-entries"] li').count()===2&&storage().revisions===3);
  await generate(b.page,'下周六14-16选1号场，18-20选4号场，不要一小时，不用候选');await b.page.getByRole('log').getByText(/不能直接交叉组合/).waitFor();check('window-specific courts require clarification',await b.page.getByTestId('queue-preview').count()===0);
  const phone=await context('phone-B',390,844);await login(phone.page,'plan_user_b');await waitScope(phone.page);await generate(phone.page,description);await phone.page.getByTestId('queue-preview').waitFor();check('390px queue preview has no horizontal overflow',await phone.page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth));await screenshot(phone.page,'proposal-phone');
  const upstream=JSON.parse(await readFile(path.join(output,'upstream-attempts.json'),'utf8'));const models=JSON.parse(await readFile(path.join(output,'model-attempts.json'),'utf8'));check('no real provider/booking/payment requests',upstream.http_attempts===0&&upstream.external_socket_attempts===0,upstream);check('fake model review and connection test exercised',models.calls>=6&&models.tests===1,models);
  await a.ctx.close();await phone.ctx.close();await b.ctx.close();
} finally {
  if(browser)await browser.close();await stop(vite);await stop(backend);await writeFile(path.join(output,'results.json'),JSON.stringify(report,null,2));
}
if(report.externalRequests.length||report.errors.length||report.checks.some(item=>!item.ok))process.exitCode=1;
console.log(JSON.stringify({output,checks:report.checks.length,passed:report.checks.filter(item=>item.ok).length,externalRequests:report.externalRequests.length,errors:report.errors.length}));
