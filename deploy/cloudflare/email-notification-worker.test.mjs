import assert from 'node:assert/strict';
import { createHmac, webcrypto } from 'node:crypto';
import test from 'node:test';
import worker from './email-notification-worker.mjs';

globalThis.crypto ??= webcrypto;
const secret = 'ab'.repeat(32);
const notification = {
  notification_id: '11111111111141118111111111111111',
  kind: 'reminder', target_date: '2026-10-26', execution_date: '2026-10-24',
  queue_version: 2, start_offset_ms: 0, credential_label: '主 Token', outcome: 'planned',
  status_label: '预计明早 07:30 起尝试预约（以实时复核为准）。',
  candidates: [{ duration_minutes: 120, scope_label: '羽毛球',
    courts: ['<img src=x onerror=alert(1)>'], start_times: ['16:00'] }],
};

function signedRequest(payload, timestamp = Math.floor(Date.now() / 1000), key = secret) {
  const body = JSON.stringify(payload);
  const signature = createHmac('sha256', Buffer.from(key, 'hex'))
    .update(`${timestamp}\n${body}`).digest('hex');
  return new Request('https://mailer.example.workers.dev/notify', {
    method: 'POST', headers: { 'X-Yumao-Timestamp': String(timestamp),
      'X-Yumao-Signature': signature, 'Content-Type': 'application/json' }, body,
  });
}

function env(send = async () => ({ messageId: 'provider-message-1' })) {
  return { BACKEND_HMAC_SECRET: secret, EMAIL_FROM: 'booking@shaxiaoguang.eu.cc',
    EMAIL_FROM_NAME: '羽毛球预约通知', EMAIL: { send } };
}

test('accepts one signed reminder and HTML-escapes candidate labels', async () => {
  const calls = [];
  const response = await worker.fetch(signedRequest(notification), env(async value => {
    calls.push(value); return { messageId: 'provider-message-1' };
  }));
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { accepted: true, message_id: 'provider-message-1' });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].from.email, 'booking@shaxiaoguang.eu.cc');
  assert.match(calls[0].html, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.equal('to' in calls[0], false);
});

test('renders a confirmed reservation using the verified court and slot', async () => {
  let sent;
  const payload={notification_id:'22222222222242228222222222222222',kind:'result',
    target_date:'2026-10-26',execution_date:'2026-10-24',credential_label:'Synthetic Token',
    outcome:'succeeded',status_label:'已抢到并核验成功',scope_label:'羽毛球',court:'2号场',
    start_time:'16:00',end_time:'18:00',duration_minutes:120,
    execution_started_at_utc_ms:1792884600000,confirmed_at_utc_ms:1792884610000};
  const response=await worker.fetch(signedRequest(payload),env(async value=>{sent=value;return{messageId:'provider-success-2'};}));
  assert.equal(response.status,200);
  assert.match(sent.subject,/2026-10-26/);
  assert.match(sent.text,/2号场 · 16:00–18:00/);
  assert.match(sent.html,/已抢到并核验成功/);
});

test('test message is clearly marked and never looks like a booking success', async () => {
  let sent;
  const response=await worker.fetch(signedRequest({notification_id:'33333333333343338333333333333333',kind:'test',outcome:'test',status_label:'测试'}),
    env(async value=>{sent=value;return{messageId:'provider-test-3'};}));
  assert.equal(response.status,200);
  assert.match(sent.subject,/邮件通知测试/);
  assert.match(sent.text,/不代表真实抢票成功/);
  assert.doesNotMatch(sent.text,/已抢到/);
});

test('rejects bad or stale signatures without calling Email Service', async () => {
  let calls = 0;
  const email = env(async () => { calls += 1; return { messageId: 'never' }; });
  const wrongKey = await worker.fetch(signedRequest(notification, undefined, 'cd'.repeat(32)), email);
  assert.equal(wrongKey.status, 401);
  const stale = await worker.fetch(signedRequest(notification, Math.floor(Date.now() / 1000) - 301), email);
  assert.equal(stale.status, 401);
  assert.equal(calls, 0);
});

test('rejects unknown paths, methods, and malformed notification content', async () => {
  const email = env(async () => ({ messageId: 'never' }));
  assert.equal((await worker.fetch(new Request('https://mailer.example.workers.dev/'), email)).status, 404);
  assert.equal((await worker.fetch(new Request('https://mailer.example.workers.dev/notify'), email)).status, 405);
  assert.equal((await worker.fetch(signedRequest({ ...notification, kind: 'arbitrary' }), email)).status, 400);
  assert.equal((await worker.fetch(signedRequest({ ...notification, candidates: Array(513).fill(notification.candidates[0]) }), email)).status, 400);
  assert.equal((await worker.fetch(new Request('https://mailer.example.workers.dev/notify', {
    method:'POST',headers:{'Content-Type':'text/plain'},body:'{}',
  }), email)).status, 415);
  assert.equal((await worker.fetch(new Request('https://mailer.example.workers.dev/notify', {
    method:'POST',headers:{'Content-Type':'application/json'},body:'{',
  }), email)).status, 401);
});

test('does not retry a provider response with an unknown send outcome', async () => {
  const response = await worker.fetch(signedRequest(notification), env(async () => {
    throw Object.assign(new Error('private provider detail'), { code: 'E_INTERNAL_SERVER_ERROR' });
  }));
  assert.equal(response.status, 409);
  assert.deepEqual(await response.json(), { error: 'provider_outcome_unknown' });
});

test('marks only an explicit rate limit as retryable', async () => {
  const response = await worker.fetch(signedRequest(notification), env(async () => {
    throw Object.assign(new Error('private provider detail'), { code: 'E_RATE_LIMIT_EXCEEDED' });
  }));
  assert.equal(response.status, 429);
  assert.deepEqual(await response.json(), { error: 'provider_retryable' });
});

test('marks known sender and payload rejections as permanent failures', async () => {
  const response = await worker.fetch(signedRequest(notification), env(async () => {
    throw Object.assign(new Error('private provider detail'), { code: 'E_SENDER_DOMAIN_NOT_AVAILABLE' });
  }));
  assert.equal(response.status, 400);
  assert.deepEqual(await response.json(), { error: 'provider_rejected' });
});
