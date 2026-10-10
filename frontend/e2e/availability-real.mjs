import { chromium } from 'playwright';
import { execFileSync, spawn } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const output=path.resolve(process.env.AVAILABILITY_QA_OUTPUT||'/tmp/yumao-availability-real-e2e');
const repo=path.resolve(fileURLToPath(new URL('../..',import.meta.url))),frontend=path.join(repo,'frontend');
const backendPort=Number(process.env.AVAILABILITY_QA_BACKEND_PORT||5828),vitePort=Number(process.env.AVAILABILITY_QA_VITE_PORT||5827);
const origin=`http://127.0.0.1:${vitePort}`;
const python=process.env.PLAN_QA_PYTHON||execFileSync('conda',['run','-n','test','python','-c','import sys;print(sys.executable)'],{encoding:'utf8'}).trim();
await mkdir(output,{recursive:false});
const report={source:'SyntheticAvailabilitySource, Fake Planning Provider, real Flask/SQLite',checks:[],screenshots:[],externalRequests:[],errors:[]};
let backend,vite,browser,manifest;
const check=(name,ok,evidence={})=>{report.checks.push({name,ok,evidence});if(!ok)throw new Error(name);};
async function ready(child,marker){
 let text='';const read=chunk=>{text+=chunk.toString().replace(/\u001b\[[0-9;]*m/g,'');};child.stdout.on('data',read);child.stderr.on('data',read);
 const deadline=Date.now()+15000;while(child.exitCode===null&&!text.includes(marker)&&Date.now()<deadline)await new Promise(r=>setTimeout(r,100));
 child.stdout.off('data',read);child.stderr.off('data',read);if(!text.includes(marker))throw new Error('isolated startup failed');return text;
}
async function stop(child){
 if(!child||child.exitCode!==null)return;
 await new Promise(resolve=>{const timer=setTimeout(()=>{if(child.exitCode===null)child.kill('SIGKILL');resolve();},3000);child.once('exit',()=>{clearTimeout(timer);resolve();});child.kill('SIGTERM');});
}
function storage(){
 return JSON.parse(execFileSync(python,['-c',`import json,sqlite3,sys
db=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True)
print(json.dumps({'plans':db.execute('SELECT count(*) FROM booking_plans').fetchone()[0], 'revisions':db.execute('SELECT count(*) FROM booking_plan_revisions').fetchone()[0], 'plan_id':db.execute('SELECT plan_id FROM booking_plans LIMIT 1').fetchone()[0] if db.execute('SELECT count(*) FROM booking_plans').fetchone()[0] else None}))`,manifest.database_path],{encoding:'utf8'}));
}
async function context(name,width=1440,height=900){
 const ctx=await browser.newContext({viewport:{width,height},timezoneId:'Asia/Shanghai'});
 await ctx.route('**/*',async route=>{if(new URL(route.request().url()).origin!==origin){report.externalRequests.push(name);await route.abort('blockedbyclient');}else await route.continue();});
 const page=await ctx.newPage();page.on('pageerror',e=>report.errors.push(e.message));return {ctx,page};
}
async function login(page,user){await page.goto(origin+'/login');await page.getByLabel('用户名').fill(user);await page.getByLabel('密码',{exact:true}).fill('Synthetic-only-password-42');await page.getByRole('button',{name:'登录',exact:true}).click();await page.getByRole('link',{name:'预约计划',exact:true}).click();await page.getByRole('heading',{name:'我的预约计划'}).waitFor();}
async function choosePlan(page){const value=await page.getByTestId('simulation-plan').locator('option').evaluateAll(options=>options.find(o=>o.value)?.value);await page.getByTestId('simulation-plan').selectOption(value);}
async function runMatch(page,scenario){await page.getByTestId('simulation-scenario').selectOption(scenario);await page.getByTestId('simulate-matches').click();await page.getByRole('region',{name:'模拟匹配结果',exact:true}).waitFor();}
async function screenshot(page,name){const file=path.join(output,name+'.jpg');await page.screenshot({path:file,fullPage:true});report.screenshots.push(file);}
try{
 backend=spawn(python,['-m','backend.tests.planning_browser_server','--simulation','--output',output,'--origin',origin,'--port',String(backendPort)],{cwd:repo,stdio:['ignore','pipe','pipe']});
 manifest=JSON.parse((await ready(backend,'"origin"')).split('\n').find(line=>line.startsWith('{')));
 vite=spawn(process.execPath,[path.join(frontend,'node_modules/vite/bin/vite.js'),'--config','e2e/plans-real.vite.config.mjs'],{cwd:frontend,env:{...Object.fromEntries(Object.entries(process.env).filter(([key])=>!key.startsWith('VITE_'))),PLAN_QA_BACKEND:`http://127.0.0.1:${backendPort}`,PLAN_QA_PORT:String(vitePort),PLAN_QA_CACHE:path.join(output,'vite-cache')},stdio:['ignore','pipe','pipe']});await ready(vite,origin);
 browser=await chromium.launch({headless:true});const a=await context('A');await login(a.page,'plan_user_a');
 check('no unsaved intent can trigger simulation',await a.page.getByTestId('simulate-matches').isDisabled());
 await a.page.getByRole('link',{name:'模型设置',exact:true}).click();await a.page.getByRole('button',{name:'添加AI模型',exact:true}).click();
 await a.page.getByLabel('显示名称').fill('合成匹配规划模型');await a.page.getByLabel('兼容接口地址').fill('https://model.example/v1');await a.page.getByLabel('模型名称',{exact:true}).fill('synthetic-planner');await a.page.getByLabel('认证方式').selectOption('none');await a.page.getByRole('button',{name:'保存模型',exact:true}).click();await a.page.getByText('模型配置已保存。').waitFor();
 await a.page.getByLabel('当前使用模型').selectOption({label:'合成匹配规划模型 · synthetic-planner'});await a.page.getByRole('button',{name:'保存模型选择'}).click();await a.page.getByText('当前模型与默认模型已更新。').waitFor();await a.page.getByRole('link',{name:'预约计划',exact:true}).click();
 await a.page.getByTestId('proposal-message').fill('下周六18:00打两个小时，东区体育馆，6号场优先，5号场备选。');await a.page.getByTestId('generate-proposal').click();await a.page.getByRole('region',{name:'AI建议预览'}).waitFor();check('AI proposal has not written plan or revision',storage().revisions===0);
 await a.page.getByTestId('confirm-save-proposal').click();await a.page.getByText('预约意向已保存 · 版本 1',{exact:true}).waitFor();check('confirmed natural-language plan persisted',storage().plans===1&&storage().revisions===1);
 await choosePlan(a.page);await runMatch(a.page,'complete');const first=a.page.getByTestId('match-candidate').first();check('preferred court and complete duration rank first',(await first.innerText()).includes('6号场')&&(await first.innerText()).includes('18:00～20:00')&&(await first.innerText()).includes('60.00 CNY'));await screenshot(a.page,'preferred-desktop');
 await runMatch(a.page,'partially_occupied');check('occupied primary uses explicitly listed backup',(await a.page.getByTestId('match-candidate').first().innerText()).includes('5号场')&&(await a.page.getByTestId('match-candidate').first().innerText()).includes('使用备选场地偏好'));await screenshot(a.page,'backup-desktop');
 await runMatch(a.page,'time_gap');check('missing intervals cannot produce a candidate',await a.page.getByTestId('match-candidate').count()===0&&await a.page.getByText(/时段断档或缺少完整/).count()>0);
 await runMatch(a.page,'no_match');check('unavailable scenario explains empty results',await a.page.getByTestId('match-candidate').count()===0&&await a.page.getByText(/组合包含明确不可用/).count()>0);await screenshot(a.page,'no-match-desktop');
 check('matching scenarios do not append revisions',storage().revisions===1);
 await a.page.getByTestId('edit-plan').click();await a.page.getByLabel('价格上限（CNY，可选）').fill('100.00');await a.page.getByRole('button',{name:'保存预约意向',exact:true}).click();await a.page.getByText('已保存预约意向 · 版本 2',{exact:true}).waitFor();await runMatch(a.page,'high_price');check('explicit budget filters high synthetic price',await a.page.getByText(/完整组合的模拟总价超过/).count()>0&&await a.page.getByTestId('match-candidate').count()===0);
 await runMatch(a.page,'price_unknown');check('missing price cannot be assumed within budget',await a.page.getByText(/缺少完整价格或货币信息/).count()>0&&await a.page.getByTestId('match-candidate').count()===0);
 await a.page.route('**/api/availability/simulation/plans/**',route=>route.abort('failed'));await a.page.getByTestId('simulate-matches').click();await a.page.getByText('模拟匹配失败，请稍后重试；预约计划未被修改。',{exact:true}).waitFor();check('network failure preserves scenario and selected plan',await a.page.getByTestId('simulation-scenario').inputValue()==='price_unknown'&&Boolean(await a.page.getByTestId('simulation-plan').inputValue()));await a.page.unroute('**/api/availability/simulation/plans/**');
 const phone=await context('phone-A',390,844);await login(phone.page,'plan_user_a');await choosePlan(phone.page);await runMatch(phone.page,'partially_occupied');check('390px result operates without horizontal overflow',await phone.page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth));await screenshot(phone.page,'backup-phone');
 const b=await context('B');await login(b.page,'plan_user_b');check('B cannot select A saved plans',await b.page.getByTestId('simulate-matches').isDisabled());
 const session=await (await b.ctx.request.get(origin+'/api/auth/session')).json();const denied=await b.ctx.request.post(origin+'/api/availability/simulation/plans/'+storage().plan_id,{headers:{Origin:origin,'X-CSRF-Token':session.csrf_token},data:{base_version:2,scenario:'complete'}});check('B cannot call simulation for A plan',denied.status()===404);
 const upstream=JSON.parse(await readFile(path.join(output,'upstream-attempts.json'),'utf8'));const models=JSON.parse(await readFile(path.join(output,'model-attempts.json'),'utf8'));check('simulation invokes no model, upstream booking payment or job',upstream.http_attempts===0&&upstream.external_socket_attempts===0&&models.calls===1&&models.tests===0,{upstream,models});check('only explicit user saves create revisions',storage().revisions===2);
 await a.ctx.close();await phone.ctx.close();await b.ctx.close();
}finally{
 if(browser)await browser.close();await stop(vite);await stop(backend);await writeFile(path.join(output,'results.json'),JSON.stringify(report,null,2));
}
if(report.externalRequests.length||report.errors.length||report.checks.some(item=>!item.ok))process.exitCode=1;
console.log(JSON.stringify({output,checks:report.checks.length,passed:report.checks.filter(c=>c.ok).length,externalRequests:report.externalRequests.length,errors:report.errors.length}));
