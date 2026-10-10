import { chromium } from 'playwright';
import { spawn, execFileSync } from 'node:child_process';
import { createServer } from 'node:net';
import { createWriteStream } from 'node:fs';
import { mkdir, mkdtemp, access, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHarness } from './harness.mjs';
import { runBaseline } from './baseline.mjs';
import { runRegressions } from './regressions.mjs';

const frontend = fileURLToPath(new URL('../', import.meta.url));
const repository = path.resolve(frontend, '..');
const out = process.env.BROWSER_QA_OUTPUT
  ? path.resolve(process.env.BROWSER_QA_OUTPUT)
  : await mkdtemp(path.join(tmpdir(), 'yumao-browser-'));
if (out === repository || out.startsWith(repository + path.sep)) {
  throw new Error('Browser artifacts must be stored outside the repository');
}
try {
  await access(path.join(out, 'results.json'));
  throw new Error('Evidence already exists; choose a fresh BROWSER_QA_OUTPUT directory');
} catch (error) {
  if (error.code !== 'ENOENT') throw error;
}
await Promise.all(['logs', 'screenshots', 'traces'].map((name) => mkdir(path.join(out, name), { recursive: true })));
const port = await new Promise((resolve, reject) => {
  const probe = createServer();
  probe.once('error', reject);
  probe.listen(0, '127.0.0.1', () => {
    const selected = probe.address().port;
    probe.close((error) => error ? reject(error) : resolve(selected));
  });
});
const base = `http://127.0.0.1:${port}`;
const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith('VITE_')));
env.BROWSER_QA_PORT = String(port);
env.BROWSER_QA_CACHE = path.join(out, 'vite-cache');
const vite = spawn(process.execPath, [path.join(frontend, 'node_modules/vite/bin/vite.js'), '--config', path.join(frontend, 'e2e/vite.config.mjs')], { cwd: frontend, env });
const viteLog = createWriteStream(path.join(out, 'logs/vite.log'));
vite.stdout.pipe(viteLog);
vite.stderr.pipe(viteLog);
let browser;
let qa;
let closingBrowser = false;
let browserBatch = 0;
let scenariosInBatch = 0;
async function launchBrowser() {
  browser = await chromium.launch({
    ...(process.env.BROWSER_EXECUTABLE_PATH ? { executablePath: process.env.BROWSER_EXECUTABLE_PATH } : {}),
    headless: true,
    args: ['--disable-background-networking', '--disable-component-update', '--disable-default-apps', '--disable-sync', '--no-first-run', '--no-proxy-server'],
  });
  const batch = ++browserBatch;
  browser.on('disconnected', () => qa?.report.browserEvents.push({ event: 'disconnected', batch, expected: closingBrowser, at: new Date().toISOString() }));
  scenariosInBatch = 0;
}
async function getBrowser() {
  // Fixed process batches limit browser lifetime independently of test outcome.
  // Unexpected disconnections still fail; no failed scenario is retried.
  if (scenariosInBatch === 12) {
    closingBrowser = true;
    await browser.close();
    closingBrowser = false;
    await launchBrowser();
  }
  scenariosInBatch += 1;
  return browser;
}
try {
  let ready = false;
  for (let attempt = 0; attempt < 120 && vite.exitCode === null; attempt++) {
    try { if ((await fetch(base)).ok) { ready = true; break; } } catch { /* Startup only. */ }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  if (!ready) throw new Error('Isolated Vite failed to start; inspect logs/vite.log');
  await launchBrowser();
  const sourceHead = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repository, encoding: 'utf8' }).trim();
  qa = createHarness({ getBrowser, base, out, sourceHead });
  qa.report.browserEvents = [];
  qa.report.browser = { name: process.env.BROWSER_EXECUTABLE_PATH ? 'local Chrome' : 'Playwright Chromium', version: browser.version(), playwright: JSON.parse(await readFile(path.join(frontend, 'node_modules/playwright/package.json'), 'utf8')).version, node: process.version, headless: true };
  qa.report.sourceStatus = execFileSync('git', ['status', '--short'], { cwd: repository, encoding: 'utf8' });
  qa.report.browserBatchSize = 12;
  if (!process.argv.includes('--only-regressions')) await runBaseline(qa);
  await runRegressions(qa);
} catch (error) {
  if (qa) qa.report.runnerError = { message: error.message };
  throw error;
} finally {
  closingBrowser = true;
  if (browser) await browser.close();
  // Only this runner's child process is stopped, after scenarios finish.
  if (vite.exitCode === null) {
    const stopped = new Promise((resolve) => vite.once('exit', resolve));
    vite.kill('SIGTERM');
    await stopped;
  }
  viteLog.end();
  if (qa) {
    const r = qa.report;
    r.summary = {
      scenarios: r.scenarios.length, screenshots: r.screenshots.length,
      checks: r.checks.length, passed: r.checks.filter((c) => c.status === 'PASS').length,
      failed: r.checks.filter((c) => c.status !== 'PASS').length,
      failedScenarios: r.scenarios.filter((s) => s.status !== 'DONE').length,
      externalRequests: r.externalRequests.length, unexpectedApiRequests: r.unexpectedApiRequests.length,
      jsExceptions: r.jsExceptions.length,
      unexpectedConsole: r.console.filter((c) => !c.expectedMockFailure).length,
      unexpectedRequestFailures: r.requestFailures.filter((f) => f.category === 'unexpected').length,
      unexpectedBrowserDisconnects: r.browserEvents.filter((event) => !event.expected).length,
      runnerErrors: r.runnerError ? 1 : 0,
    };
    await writeFile(path.join(out, 'results.json'), JSON.stringify(r, null, 2));
    console.log(JSON.stringify({ browser: r.browser, summary: r.summary, output: out }, null, 2));
    if (Object.entries(r.summary).some(([key, value]) => ['failed', 'failedScenarios', 'externalRequests', 'unexpectedApiRequests', 'jsExceptions', 'unexpectedConsole', 'unexpectedRequestFailures', 'unexpectedBrowserDisconnects', 'runnerErrors'].includes(key) && value > 0)) process.exitCode = 1;
  }
}
