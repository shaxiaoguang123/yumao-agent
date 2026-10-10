import { writeFile } from 'node:fs/promises';
import path from 'node:path';
import { SYNTHETIC_CSRF, SYNTHETIC_CODE, SYNTHETIC_PASSWORD, SYNTHETIC_TOKEN, clone, credential, fixtures, viewports } from './fixtures.mjs';

export function createHarness({ getBrowser, base: BASE, out: OUT, sourceHead }) {
  const report = { sourceHead, base: BASE, browser: {}, screenshots: [], checks: [], scenarios: [], externalRequests: [], unexpectedApiRequests: [], jsExceptions: [], console: [], requestFailures: [] };
function check(scenario, name, passed, evidence = {}) {
  report.checks.push({ scenario, name, status: passed ? 'PASS' : 'FAIL', evidence });
}
function safe(value) {
  return String(value).replaceAll(SYNTHETIC_CODE, '[SYNTHETIC_CODE_REDACTED]').replaceAll(SYNTHETIC_TOKEN, '[SYNTHETIC_TOKEN_REDACTED]').replaceAll(SYNTHETIC_PASSWORD, '[SYNTHETIC_PASSWORD_REDACTED]').replaceAll(SYNTHETIC_CSRF, '[SYNTHETIC_CSRF_REDACTED]');
}
async function contextFor(name, role, viewport = viewports[0], options = {}) {
  const browser = await getBrowser();
  const state = { role, credentials: clone(fixtures), requests: [], listDelay: 0, listError: false, listNetworkError: false, sessionError: false, inviteDelay: 0, inviteOutcome: 'success', createDelay: 0, createError: false, removeError: false, rotationError: false, loginOutcome: 'success', registerOutcome: 'success', passwordOutcome: 'error', passwordDelay: 0, logoutOutcome: 'success', ...options };
  const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height }, locale: 'zh-CN', timezoneId: 'Asia/Shanghai', reducedMotion: 'reduce', serviceWorkers: 'block', permissions: ['clipboard-read', 'clipboard-write'] });
  const pendingRoutes = new Set();
  const requestRecords = new WeakMap();
  await context.tracing.start({ screenshots: true, snapshots: true, sources: false });
  const session = () => state.role === 'anonymous' ? { authenticated: false } : { authenticated: true, user: { user_id: `synthetic-${state.role}`, username: state.role === 'admin' ? 'visual_admin' : 'visual_user', role: state.role }, csrf_token: SYNTHETIC_CSRF };
  await context.routeWebSocket('**/*', (ws) => {
    const url = new URL(ws.url());
    if (url.protocol === 'ws:' && url.host === new URL(BASE).host) ws.connectToServer();
    else { report.externalRequests.push({ scenario: name, kind: 'websocket', origin: url.origin }); ws.close(); }
  });
  const handleRoute = async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== BASE) {
      report.externalRequests.push({ scenario: name, kind: request.resourceType(), origin: url.origin });
      await route.abort('blockedbyclient'); return;
    }
    if (!url.pathname.startsWith('/api/')) { await route.continue(); return; }
    const record = { method: request.method(), path: url.pathname, status: null };
    requestRecords.set(request, record);
    if (url.search || url.hash) { report.unexpectedApiRequests.push({ scenario: name, reason: 'unexpected API query', path: url.pathname }); await route.abort('blockedbyclient'); return; }
    if (!['GET', 'HEAD', 'OPTIONS'].includes(record.method) && !['/api/auth/login', '/api/auth/register'].includes(record.path)) record.csrfValid = request.headers()['x-csrf-token'] === SYNTHETIC_CSRF;
    state.requests.push(record);
    const reply = async (status, payload = {}, raw = null) => {
      record.status = status;
      await route.fulfill({ status, contentType: raw === null ? 'application/json' : 'text/plain', ...(status === 204 ? { body: '' } : { body: raw === null ? JSON.stringify(payload) : raw }) });
    };
    const delay = async (ms) => { if (ms) await new Promise((resolve) => setTimeout(resolve, ms)); };
    if (url.pathname === '/api/auth/session' && record.method === 'GET') {
      await reply(state.sessionError ? 503 : 200, state.sessionError ? { error: 'service_unavailable' } : session()); return;
    }
    if (url.pathname === '/api/auth/login' && record.method === 'POST') {
      if (state.loginOutcome === 'error') await reply(401, { error: 'invalid_credentials' });
      else { state.role = 'user'; await reply(200, session()); } return;
    }
    if (url.pathname === '/api/auth/register' && record.method === 'POST') {
      await reply(state.registerOutcome === 'error' ? 409 : 201, state.registerOutcome === 'error' ? { error: 'username_unavailable' } : { registered: true }); return;
    }
    if (url.pathname === '/api/auth/change-password' && record.method === 'POST') {
      await delay(state.passwordDelay);
      if (state.passwordOutcome === 'error') await reply(429, { error: 'rate_limited' });
      else { state.role = 'anonymous'; await reply(204); } return;
    }
    if (url.pathname === '/api/auth/logout' && record.method === 'POST') {
      if (state.logoutOutcome === 'error') await reply(503, { error: 'service_unavailable' });
      else { state.role = 'anonymous'; await reply(204); } return;
    }
    if (url.pathname === '/api/admin/invitations' && record.method === 'POST') {
      await delay(state.inviteDelay);
      if (state.inviteOutcome === 'network') { record.status = 'MOCK_NETWORK_ABORT'; await route.abort('failed'); }
      else if (state.inviteOutcome === 'timeout') { record.status = 'MOCK_NETWORK_TIMEOUT'; await route.abort('timedout'); }
      else if (state.inviteOutcome === 'malformed-json') await reply(201, {}, '{synthetic-invalid-json');
      else if (state.inviteOutcome === 'invalid-schema') await reply(201, { invitation_code: SYNTHETIC_CODE });
      else if (typeof state.inviteOutcome === 'number') { if (state.inviteOutcome === 401) state.role = 'anonymous'; await reply(state.inviteOutcome, { error: state.inviteOutcome === 401 ? 'session_expired' : 'synthetic_expected_error' }); }
      else await reply(201, { invitation_code: SYNTHETIC_CODE, expires_at_utc_ms: Date.UTC(2026, 9, 10, 12) });
      return;
    }
    if (url.pathname === '/api/credentials' && record.method === 'GET') {
      await delay(state.listDelay); if (state.listNetworkError) { record.status = 'MOCK_NETWORK_ABORT'; await route.abort('failed'); return; } await reply(state.listError ? 503 : 200, state.listError ? { error: 'upstream_unavailable' } : { credentials: state.credentials }); return;
    }
    if (url.pathname === '/api/credentials' && record.method === 'POST') {
      await delay(state.createDelay);
      if (state.createError) await reply(409, { error: 'credential_account_already_configured' });
      else { const item = credential('visual-created', '合成新凭据'); state.credentials.push(item); await reply(201, { credential: item }); } return;
    }
    const matched = url.pathname.match(/^\/api\/credentials\/([^/]+)(?:\/(validate|rotate-token))?$/);
    if (matched) {
      if (matched[2] ? record.method !== 'POST' : !['PATCH', 'DELETE'].includes(record.method)) {
        report.unexpectedApiRequests.push({ scenario: name, method: record.method, path: record.path });
        await reply(501, { error: 'unmocked_api' }); return;
      }
      const item = state.credentials.find((row) => row.credential_id === matched[1]);
      if (!item) { await reply(404, { error: 'credential_not_found' }); return; }
      if (!matched[2] && record.method === 'DELETE') {
        if (state.removeError) await reply(409, { error: 'credential_version_conflict' });
        else { state.credentials = state.credentials.filter((row) => row !== item); await reply(204); }
      } else if (!matched[2] && record.method === 'PATCH') {
        item.enabled = !item.enabled; item.requires_revalidation = item.enabled; item.credential_version += 1; await reply(200, { credential: item });
      } else if (matched[2] === 'rotate-token' && record.method === 'POST') {
        if (state.rotationError) await reply(409, { error: 'credential_account_mismatch' });
        else { item.credential_version += 1; await reply(200, { credential: item }); }
      } else if (matched[2] === 'validate' && record.method === 'POST') await reply(200, { credential: item });
      else { report.unexpectedApiRequests.push({ scenario: name, method: record.method, path: record.path }); await reply(501, { error: 'unmocked_api' }); }
      return;
    }
    report.unexpectedApiRequests.push({ scenario: name, method: record.method, path: record.path });
    await reply(501, { error: 'unmocked_api' });
  };
  await context.route('**/*', (route) => {
    const task = handleRoute(route);
    pendingRoutes.add(task);
    task.then(() => pendingRoutes.delete(task), () => pendingRoutes.delete(task));
    return task;
  });
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  page.on('pageerror', (error) => report.jsExceptions.push({ scenario: name, message: safe(error.message) }));
  page.on('console', (msg) => {
    if (msg.type() === 'error' || msg.type() === 'warning') report.console.push({ scenario: name, type: msg.type(), message: safe(msg.text()), url: msg.location().url ? new URL(msg.location().url).pathname : '', expectedMockFailure: /^Failed to load resource:/.test(msg.text()) && state.requests.some((r) => r.path === new URL(msg.location().url || BASE).pathname && (r.status >= 400 || String(r.status).startsWith('MOCK_'))) });
  });
  page.on('requestfailed', (request) => {
    const record = requestRecords.get(request);
    const reason = request.failure()?.errorText;
    const category = String(record?.status).startsWith('MOCK_') ? 'injected network failure'
      : record?.status === 204 && reason === 'net::ERR_ABORTED' ? '204 lifecycle cancellation' : 'unexpected';
    report.requestFailures.push({ scenario: name, path: new URL(request.url()).pathname, reason, category });
  });
  return { browser, context, page, state, name, viewport, pendingRoutes };
}
async function screenshot(ctx, name, options = {}) {
  const file = path.join(OUT, 'screenshots', `${name}.png`);
  await ctx.page.screenshot({ path: file, fullPage: true, animations: 'disabled', mask: [ctx.page.getByTestId('invitation-code'), ctx.page.locator('input[type=password]')], ...options });
  report.screenshots.push({ name, file, route: new URL(ctx.page.url()).pathname, viewport: ctx.viewport.name, width: ctx.viewport.width, height: ctx.viewport.height, role: ctx.state.role });
}
async function layout(ctx) {
  const geometry = await ctx.page.evaluate(() => {
    const width = document.documentElement.clientWidth;
    const shown = (e) => !!(e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden');
    const describe = (e) => ({ tag: e.tagName.toLowerCase(), class: e.className, testid: e.getAttribute('data-testid'), left: Math.round(e.getBoundingClientRect().left), right: Math.round(e.getBoundingClientRect().right), width: Math.round(e.getBoundingClientRect().width), height: Math.round(e.getBoundingClientRect().height) });
    const overflowing = [...document.querySelectorAll('header,nav,a,button,input,h1,h2,h3,article,section,dl,dd')].filter(shown).filter((e) => e.getBoundingClientRect().right > width + 1 || e.getBoundingClientRect().left < -1).map(describe);
    const clipped = [...document.querySelectorAll('a,button,h1,h2,h3,label,dt,dd')].filter(shown).filter((e) => ['hidden','clip'].includes(getComputedStyle(e).overflowX) && e.scrollWidth > e.clientWidth + 1).map(describe);
    const nav = [...document.querySelectorAll('.topbar a')].map((e) => ({ text: e.textContent.trim(), ...describe(e) }));
    const controls = [...document.querySelectorAll('button,input')].filter(shown).map(describe);
    return { viewport: width, documentScrollWidth: Math.max(document.body.scrollWidth, document.documentElement.scrollWidth), overflowing, clipped, nav, controls };
  });
  check(ctx.name, 'horizontal overflow', geometry.documentScrollWidth <= geometry.viewport, geometry);
  check(ctx.name, 'CSS-clipped text', geometry.clipped.length === 0, { clipped: geometry.clipped });
  return geometry;
}
async function tabs(ctx) {
  const sequence = [];
  for (let i = 0; i < 9; i++) {
    await ctx.page.keyboard.press('Tab');
    sequence.push(await ctx.page.evaluate(() => {
      const e = document.activeElement; const c = getComputedStyle(e); const r = e.getBoundingClientRect();
      return { tag: e.tagName.toLowerCase(), label: e.getAttribute('data-testid') || e.getAttribute('name') || (e.tagName === 'INPUT' ? e.getAttribute('type') : e.textContent.trim().slice(0, 48)), outlineStyle: c.outlineStyle, outlineWidth: c.outlineWidth, boxShadow: c.boxShadow, visible: r.width > 0 && r.height > 0, focusVisible: e.matches(':focus-visible') };
    }));
  }
  const controls = sequence.filter((item) => ['a','input','button'].includes(item.tag));
  check(ctx.name, 'keyboard Tab and focus indication', controls.length > 0 && controls.every((item) => item.visible && (item.outlineStyle !== 'none' && parseFloat(item.outlineWidth) > 0 || item.boxShadow !== 'none')), { sequence });
}
async function privacy(ctx) {
  const data = await ctx.page.evaluate(() => ({ localKeys: Object.keys(localStorage), sessionKeys: Object.keys(sessionStorage), urlHasQuery: Boolean(location.search || location.hash) }));
  check(ctx.name, 'no persistent synthetic credentials or URL data', data.localKeys.length === 0 && data.sessionKeys.length === 0 && !data.urlHasQuery, data);
  const mutations = ctx.state.requests.filter((item) => 'csrfValid' in item);
  check(ctx.name, 'authenticated mutations carry Session CSRF', mutations.every((item) => item.csrfValid), { mutations });
}
async function scenario(name, role, fn, options = {}, viewport = viewports[0]) {
  // Every invocation runs every selected scenario in a fresh Context.
  const ctx = await contextFor(name, role, viewport, options);
  try { await fn(ctx); await privacy(ctx); report.scenarios.push({ name, status: 'DONE', requests: ctx.state.requests }); }
  catch (error) { report.scenarios.push({ name, status: 'FAIL', error: safe(error.message), requests: ctx.state.requests }); check(name, 'scenario completed', false, { error: safe(error.message) }); }
  finally {
    // Keep interception active until delayed Mock replies settle, including
    // requests deliberately left pending when the view is unmounted.
    while (ctx.pendingRoutes.size) await Promise.all([...ctx.pendingRoutes]);
    try { await ctx.context.tracing.stop({ path: path.join(OUT, 'traces', `${name}.zip`) }); }
    catch (error) { check(name, 'trace saved', false, { error: safe(error.message) }); }
    await ctx.context.close();
    console.log(JSON.stringify({ scenario: name, status: report.scenarios.at(-1).status }));
    await writeFile(path.join(OUT, 'results.json'), JSON.stringify(report, null, 2));
    if (!ctx.browser.isConnected()) throw new Error('Browser disconnected; remaining scenarios were not run');
  }
}
const waitCredentials = (page) => page.getByTestId('credential-card-visual-confirmed').waitFor();
const count = (ctx, path, method = 'POST') => ctx.state.requests.filter((r) => r.path === path && r.method === method).length;

return { BASE, OUT, report, scenario, check, screenshot, layout, tabs, waitCredentials, count };
}
