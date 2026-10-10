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
async function login(page,user) {await page.goto(origin+'/login');await page.getByLabel('用户名').fill(user);await page.getByLabel('密码',{exact:true}).fill('Synthetic-only-password-42');await page.getByRole('button',{name:'登录',exact:true}).click();await page.getByRole('link',{name:'预约计划',exact:true}).click();await page.getByRole('heading',{name:'我的预约计划'}).waitFor();}
async function screenshot(page,name) {const file=path.join(output,name+'.jpg');await page.screenshot({path:file,fullPage:true});report.screenshots.push(file);}
const description='下周六18:00打两个小时，东区体育馆，6号场优先，5号场备选。';
const editDescription='把开始时间改成19:00，5号场改为第一优先级。';
async function generate(page,message) {await page.getByTestId('proposal-message').fill(message);await page.getByTestId('generate-proposal').click();}
async function selectExisting(page) {const values=await page.getByTestId('proposal-target').locator('option').evaluateAll(items=>items.map(item=>({value:item.value,label:item.textContent})));await page.getByTestId('proposal-target').selectOption(values.find(item=>item.label.startsWith('编辑：')).value);}
try {
  backend=spawn(python,['-m','backend.tests.planning_browser_server','--output',output,'--origin',origin,'--port',String(backendPort)],{cwd:repo,stdio:['ignore','pipe','pipe']});
  manifest=JSON.parse((await ready(backend,'"origin"')).split('\n').find(line=>line.startsWith('{')));
  vite=spawn(process.execPath,[path.join(frontend,'node_modules/vite/bin/vite.js'),'--config','e2e/plans-real.vite.config.mjs'],{cwd:frontend,env:{...Object.fromEntries(Object.entries(process.env).filter(([key])=>!key.startsWith('VITE_'))),PLAN_QA_BACKEND:`http://127.0.0.1:${backendPort}`,PLAN_QA_PORT:String(vitePort),PLAN_QA_CACHE:path.join(output,'vite-cache')},stdio:['ignore','pipe','pipe']});
  await ready(vite,origin);
  browser=await chromium.launch({headless:true});
  const a=await context('A');await login(a.page,'plan_user_a');
  await generate(a.page,description);await a.page.getByText(/尚未配置 AI 模型/).first().waitFor();check('missing model leaves manual create usable',await a.page.getByTestId('new-plan').isEnabled());
  await a.page.getByRole('link',{name:'模型设置',exact:true}).click();
  await a.page.getByRole('button',{name:'添加AI模型',exact:true}).click();
  await a.page.getByLabel('显示名称').fill('合成规划模型');await a.page.getByLabel('兼容接口地址').fill('https://model.example/v1');await a.page.getByLabel('模型名称',{exact:true}).fill('synthetic-planner');await a.page.getByLabel(/^API Key/).fill('Synthetic-model-key-only-42');
  await a.page.getByRole('button',{name:'保存模型',exact:true}).click();await a.page.getByText('模型配置已保存。').waitFor();
  // The success notice is set before the asynchronous model-list refresh completes.
  await a.page.getByText('API Key 已配置（不会显示密钥）',{exact:false}).waitFor();
  check('model config stores encrypted secret without echo',await a.page.getByText('API Key 已配置（不会显示密钥）',{exact:false}).count()===1&&storage().plaintext_keys===0);
  await a.page.getByLabel('当前使用模型').selectOption({label:'合成规划模型 · synthetic-planner'});await a.page.getByLabel('默认模型').selectOption({label:'合成规划模型 · synthetic-planner'});await a.page.getByRole('button',{name:'保存模型选择'}).click();await a.page.getByText('当前模型与默认模型已更新。').waitFor();
  await a.page.getByRole('button',{name:'测试连接',exact:true}).click();await a.page.getByText('模型连接成功。').waitFor();check('explicit provider connection test reaches fake adapter',true);
  await a.page.getByTestId('test-model-parsing').click();await a.page.getByText('连接正常且计划解析成功。测试不会保存预约计划。').waitFor();check('explicit capability test validates synthetic plan without a write',storage().plans===0&&storage().revisions===0);
  await a.page.getByRole('button',{name:'添加AI模型',exact:true}).click();await a.page.getByLabel('显示名称').fill('备用合成模型');await a.page.getByLabel('兼容接口地址').fill('https://alternate.example/v1');await a.page.getByLabel('模型名称',{exact:true}).fill('synthetic-alternate');await a.page.getByLabel('认证方式').selectOption('none');await a.page.getByRole('button',{name:'保存模型',exact:true}).click();await a.page.getByText('模型配置已保存。').waitFor();check('multiple configs persisted',storage().models===2);await screenshot(a.page,'models-desktop');
  await a.page.getByRole('link',{name:'预约计划',exact:true}).click();await generate(a.page,'下周六18:00打两个小时，6号场优先，5号场备选。');await a.page.getByRole('heading',{name:'还需要补充信息'}).waitFor();check('missing venue requests clarification',storage().plans===0);
  await a.page.getByTestId('proposal-answer').fill('东区体育馆。');await a.page.getByTestId('continue-proposal').click();await a.page.getByRole('region',{name:'AI建议预览'}).waitFor();check('venue-only supplement retains original date time and court',storage().plans===0);
  await a.page.getByTestId('restart-conversation').click();await generate(a.page,'下周六18:00打两个小时。');await a.page.getByRole('heading',{name:'还需要补充信息'}).waitFor();await a.page.getByTestId('proposal-answer').fill('东区体育馆。');await a.page.getByTestId('continue-proposal').click();await a.page.getByText('请补充场地偏好或同场馆备用意愿。',{exact:true}).waitFor();check('second clarification does not write SQLite',storage().revisions===0);
  await a.page.getByTestId('proposal-answer').fill('6号场优先，5号场备选。');await a.page.getByTestId('continue-proposal').click();await a.page.getByRole('region',{name:'AI建议预览'}).waitFor();check('two supplements produce complete proposal without automatic save',storage().plans===0);

  await screenshot(a.page,'proposal-desktop');await a.page.getByTestId('confirm-save-proposal').click();await a.page.getByText('预约意向已保存 · 版本 1',{exact:true}).waitFor();check('explicit confirmation writes SQLite',storage().plans===1&&storage().revisions===1);
  await a.page.reload();await a.page.getByTestId('history-plan').waitFor();check('reload reads saved plan',true);
  await selectExisting(a.page);await generate(a.page,editDescription);await a.page.getByRole('region',{name:'AI建议预览'}).waitFor();check('edit preview precedes revision append',storage().revisions===1);await a.page.getByTestId('confirm-save-proposal').click();await a.page.getByText('预约意向已保存 · 版本 2',{exact:true}).waitFor();check('confirmed AI edit appends revision',storage().revisions===2);
  await a.page.getByTestId('history-plan').click();await a.page.getByRole('heading',{name:'版本历史',exact:true}).waitFor();await screenshot(a.page,'history-desktop');check('history opens after AI edit',true);await a.page.getByRole('button',{name:'关闭历史'}).click();
  await generate(a.page,'模拟失败，请保留我的描述。');await a.page.getByText(/生成建议失败/).waitFor();check('model failure retains input',await a.page.getByTestId('proposal-message').inputValue()==='模拟失败，请保留我的描述。');
  await generate(a.page,'把开始时间改成20:00。');await a.page.getByRole('region',{name:'AI建议预览'}).waitFor();
  const concurrent=await a.ctx.newPage();await concurrent.goto(origin+'/plans');await concurrent.getByTestId('edit-plan').click();await concurrent.getByLabel('场馆名称或描述（人工偏好）').fill('并发人工偏好');await concurrent.getByRole('button',{name:'保存预约意向',exact:true}).click();await concurrent.getByText('已保存预约意向 · 版本 3',{exact:true}).waitFor();await concurrent.close();
  await a.page.getByTestId('confirm-save-proposal').click();await a.page.getByText('保存时检测到版本冲突。你的描述和建议均已保留。',{exact:true}).waitFor();check('409 preserves proposal and does not overwrite',await a.page.getByTestId('proposal-message').inputValue()==='把开始时间改成20:00。'&&await a.page.getByRole('region',{name:'AI建议预览'}).isVisible()&&storage().revisions===3);await screenshot(a.page,'conflict-desktop');
  const phone=await context('phone-A',390,844);await login(phone.page,'plan_user_a');await generate(phone.page,description);await phone.page.getByRole('region',{name:'AI建议预览'}).waitFor();check('390px proposal has no horizontal overflow',await phone.page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth));await screenshot(phone.page,'proposal-phone');
  const b=await context('B');await login(b.page,'plan_user_b');check('B cannot see A plans',await b.page.getByTestId('edit-plan').count()===0);await b.page.getByRole('link',{name:'模型设置',exact:true}).click();await b.page.getByText('还没有配置可用模型').waitFor();check('B cannot see A models',await b.page.getByRole('heading',{name:'合成规划模型',exact:true}).count()===0);
  const upstream=JSON.parse(await readFile(path.join(output,'upstream-attempts.json'),'utf8'));const models=JSON.parse(await readFile(path.join(output,'model-attempts.json'),'utf8'));check('no real provider/booking/payment requests',upstream.http_attempts===0&&upstream.external_socket_attempts===0,upstream);check('Fake model generation and connection test exercised',models.calls>=6&&models.tests===1,models);
  await a.ctx.close();await phone.ctx.close();await b.ctx.close();
} finally {
  if(browser)await browser.close();await stop(vite);await stop(backend);await writeFile(path.join(output,'results.json'),JSON.stringify(report,null,2));
}
if(report.externalRequests.length||report.errors.length||report.checks.some(item=>!item.ok))process.exitCode=1;
console.log(JSON.stringify({output,checks:report.checks.length,passed:report.checks.filter(item=>item.ok).length,externalRequests:report.externalRequests.length,errors:report.errors.length}));
