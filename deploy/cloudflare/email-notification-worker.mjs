const MAX_BODY_BYTES = 64 * 1024;
const MAX_CLOCK_SKEW_SECONDS = 300;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const TIME = /^(?:[01]\d|2[0-3]):[0-5]\d$/;
const PROVIDER_CODE = /^[A-Z0-9_]{1,48}$/;
const PERMANENT_SEND_ERRORS = new Set([
  "E_ACCOUNT_SUSPENDED", "E_SENDER_DOMAIN_NOT_AVAILABLE", "E_SENDER_NOT_VERIFIED",
  "E_CONTENT_TOO_LARGE", "E_DELIVERY_FAILED", "E_HEADER_NOT_ALLOWED",
  "E_HEADER_USE_API_FIELD", "E_HEADER_VALUE_INVALID", "E_VALIDATION_ERROR",
  "E_FIELD_MISSING", "E_TOO_MANY_RECIPIENTS", "E_TOO_MANY_ATTACHMENTS",
  "E_RECIPIENT_NOT_ALLOWED", "E_RECIPIENT_SUPPRESSED", "E_DAILY_LIMIT_EXCEEDED",
]);

function response(status, body) {
  return Response.json(body, { status, headers: { "Cache-Control": "no-store" } });
}

function providerHint(error) {
  if (error?.code === "E_RATE_LIMIT_EXCEEDED") return "rate_limited";
  if (error?.code === "E_DAILY_LIMIT_EXCEEDED") return "daily_limit";
  if (error?.code === "E_INTERNAL_SERVER_ERROR") return "service_unavailable";
  if (error?.code === "E_ACCOUNT_SUSPENDED") return "account_suspended";
  if (error?.code === "E_SENDER_DOMAIN_NOT_AVAILABLE" || error?.code === "E_SENDER_NOT_VERIFIED") return "sender_domain";
  if (error?.code === "E_RECIPIENT_NOT_ALLOWED" || error?.code === "E_RECIPIENT_SUPPRESSED") return "recipient";
  const message = typeof error?.message === "string" ? error.message.toLowerCase() : "";
  if (message.includes("paid") || message.includes("entitl") || message.includes("workers plan")) return "plan_required";
  if (message.includes("sender") || message.includes("domain") || message.includes("verified")) return "sender_domain";
  if (message.includes("recipient") || message.includes("destination") || message.includes("allowed")) return "recipient";
  if (message.includes("rate") || message.includes("limit") || message.includes("throttl")) return "rate_limited";
  if (message.includes("unavailable") || message.includes("internal") || message.includes("temporar")) return "service_unavailable";
  return "unclassified";
}

function sendFailure(error) {
  const providerCode = typeof error?.code === "string" && PROVIDER_CODE.test(error.code)
    ? error.code : "UNCLASSIFIED";
  const details = { provider_code: providerCode, provider_hint: providerHint(error) };
  if (providerCode === "E_RATE_LIMIT_EXCEEDED") {
    return response(429, { error: "provider_retryable", ...details });
  }
  if (PERMANENT_SEND_ERRORS.has(providerCode)) {
    return response(400, { error: "provider_rejected", ...details });
  }
  return response(409, { error: "provider_outcome_unknown", ...details });
}

async function readBoundedBody(request) {
  const declared = Number(request.headers.get("Content-Length"));
  if (Number.isFinite(declared) && declared > MAX_BODY_BYTES) return null;
  if (!request.body) return "";
  const reader = request.body.getReader();
  const chunks = [];
  let size = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > MAX_BODY_BYTES) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
}

function decodeHex(value) {
  if (typeof value !== "string" || !/^(?:[0-9a-f]{2})+$/.test(value)) return null;
  return Uint8Array.from(value.match(/.{2}/g), pair => Number.parseInt(pair, 16));
}

async function authorized(request, body, secret, nowSeconds) {
  const timestamp = request.headers.get("X-Yumao-Timestamp") || "";
  const signature = decodeHex(request.headers.get("X-Yumao-Signature"));
  if (!/^\d{10}$/.test(timestamp) || !signature
      || Math.abs(nowSeconds - Number(timestamp)) > MAX_CLOCK_SKEW_SECONDS) return false;
  const keyBytes = decodeHex(secret);
  if (!keyBytes) return false;
  const key = await crypto.subtle.importKey("raw", keyBytes, { name: "HMAC", hash: "SHA-256" }, false, ["verify"]);
  return crypto.subtle.verify("HMAC", key, signature,
    new TextEncoder().encode(`${timestamp}\n${body}`));
}

function cleanText(value, maxLength = 160) {
  return typeof value === "string" && value.length <= maxLength
    && !/[\u0000-\u001f\u007f]/.test(value);
}

function onlyKeys(value, allowed) {
  return Object.keys(value).every(key => allowed.includes(key));
}

function validCandidate(candidate) {
  return candidate && typeof candidate === "object"
    && [60, 120].includes(candidate.duration_minutes)
    && cleanText(candidate.scope_label, 100)
    && Array.isArray(candidate.courts) && candidate.courts.length <= 10
    && candidate.courts.every(court => cleanText(court, 80))
    && Array.isArray(candidate.start_times) && candidate.start_times.length <= 13
    && candidate.start_times.every(value => TIME.test(value));
}

function validPayload(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)
      || !cleanText(payload.notification_id, 64) || !cleanText(payload.status_label, 180)) return false;
  if (payload.kind === "test") {
    return onlyKeys(payload, ["notification_id", "kind", "outcome", "status_label"])
      && payload.outcome === "test";
  }
  if (!DATE.test(payload.target_date) || !DATE.test(payload.execution_date)
      || !cleanText(payload.credential_label, 80)) return false;
  if (payload.kind === "reminder") {
    return onlyKeys(payload, ["notification_id", "kind", "target_date", "execution_date",
      "credential_label", "outcome", "status_label", "queue_version", "start_offset_ms", "candidates"])
      && payload.outcome === "planned" && Number.isSafeInteger(payload.queue_version)
      && payload.queue_version > 0 && Number.isSafeInteger(payload.start_offset_ms)
      && payload.start_offset_ms >= 0 && payload.start_offset_ms <= 60_000
      && Array.isArray(payload.candidates)
      && payload.candidates.length > 0 && payload.candidates.length <= 512
      && payload.candidates.every(validCandidate);
  }
  if (payload.kind === "result") {
    if (!onlyKeys(payload, ["notification_id", "kind", "target_date", "execution_date",
      "credential_label", "outcome", "status_label", "scope_label", "court", "start_time",
      "end_time", "duration_minutes", "confirmed_at_utc_ms", "execution_started_at_utc_ms"])
      || !["succeeded", "failed", "empty", "stale", "needs_attention", "not_executed"]
      .includes(payload.outcome)) return false;
    return payload.outcome !== "succeeded"
      || (cleanText(payload.scope_label, 100) && cleanText(payload.court, 80)
        && TIME.test(payload.start_time) && TIME.test(payload.end_time)
        && Number.isSafeInteger(payload.duration_minutes)
        && Number.isSafeInteger(payload.confirmed_at_utc_ms));
  }
  return false;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

function render(payload) {
  if (payload.kind === "test") {
    return {
      subject: "【羽毛球预约】邮件通知测试",
      text: "这是一封羽毛球预约工作台的邮件通知测试。此邮件不代表真实抢票成功，也没有触发预约或付款。时间均为北京时间。\n查看预约工作台：https://yumao.shaxiaoguang.eu.cc/plans",
      html: "<h2>邮件通知测试</h2><p>这是一封羽毛球预约工作台的测试邮件。</p><p><strong>此邮件不代表真实抢票成功，也没有触发预约或付款。</strong></p><p>时间均为北京时间。</p><p><a href=\"https://yumao.shaxiaoguang.eu.cc/plans\">查看预约工作台</a></p>",
    };
  }
  const subject = payload.kind === "reminder"
    ? `【羽毛球预约提醒】${payload.target_date}`
    : `【羽毛球预约结果】${payload.target_date}`;
  const text = [`预约场地日期：${payload.target_date}`, `抢票执行日期：${payload.execution_date}`,
    `凭据：${payload.credential_label}`, `状态：${payload.status_label}`];
  const details = [];
  if (payload.kind === "reminder") {
    const startTime = payload.start_offset_ms
      ? `07:30 后延迟 ${payload.start_offset_ms} 毫秒` : "07:30";
    text.push(`预计开始尝试：${startTime}`);
    details.push(`<li>预计开始尝试：${escapeHtml(startTime)}</li>`);
    for (const candidate of payload.candidates) {
      const duration = candidate.duration_minutes === 120 ? "两小时" : "一小时";
      const line = `${duration} · ${candidate.scope_label} · ${candidate.courts.join("、") || "场地未指定"} · ${candidate.start_times.join("、") || "时间未指定"}`;
      text.push(line);
      details.push(`<li>${escapeHtml(line)}</li>`);
    }
  } else if (payload.outcome === "succeeded") {
    const line = `预约成功：${payload.court} · ${payload.start_time}–${payload.end_time}（${payload.scope_label}）`;
    const confirmedAt = new Intl.DateTimeFormat("zh-CN", {
      timeZone: "Asia/Shanghai", dateStyle: "short", timeStyle: "medium",
    }).format(payload.confirmed_at_utc_ms);
    const startedAt = Number.isSafeInteger(payload.execution_started_at_utc_ms)
      ? new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", dateStyle: "short", timeStyle: "medium" }).format(payload.execution_started_at_utc_ms)
      : null;
    text.push(line, ...(startedAt ? [`开始尝试时间：${startedAt}`] : []), `订单核验时间：${confirmedAt}`);
    details.push(`<li>${escapeHtml(line)}</li>`,
      ...(startedAt ? [`<li>开始尝试时间：${escapeHtml(startedAt)}</li>`] : []),
      `<li>订单核验时间：${escapeHtml(confirmedAt)}</li>`);
  }
  const plainText = `${text.join("\n")}\n\n时间均为北京时间。\n查看预约工作台：https://yumao.shaxiaoguang.eu.cc/plans`;
  const html = `<h2>${escapeHtml(subject)}</h2><p>${escapeHtml(payload.status_label)}</p><ul>${details.join("")}</ul><p>预约场地日期：${escapeHtml(payload.target_date)}<br>抢票执行日期：${escapeHtml(payload.execution_date)}<br>凭据：${escapeHtml(payload.credential_label)}</p><p>时间均为北京时间。</p><p><a href="https://yumao.shaxiaoguang.eu.cc/plans">查看预约工作台</a></p>`;
  return { subject, text: plainText, html };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/notify") return response(404, { error: "not_found" });
    if (request.method !== "POST") return response(405, { error: "method_not_allowed" });
    if (!request.headers.get("Content-Type")?.toLowerCase().startsWith("application/json")) {
      return response(415, { error: "unsupported_media_type" });
    }
    let body;
    try { body = await readBoundedBody(request); }
    catch { return response(400, { error: "invalid_body" }); }
    if (body === null || body.length === 0) return response(413, { error: "invalid_body" });
    try {
      const nowSeconds = Math.floor(Date.now() / 1000);
      if (!await authorized(request, body, env.BACKEND_HMAC_SECRET, nowSeconds)) {
        return response(401, { error: "unauthorized" });
      }
    } catch {
      return response(401, { error: "unauthorized" });
    }
    let payload;
    try { payload = JSON.parse(body); } catch { return response(400, { error: "invalid_body" }); }
    if (!validPayload(payload)) return response(400, { error: "invalid_notification" });
    try {
      const message = render(payload);
      const sent = await env.EMAIL.send({
        from: { email: env.EMAIL_FROM, name: env.EMAIL_FROM_NAME },
        subject: message.subject,
        text: message.text,
        html: message.html,
      });
      if (typeof sent?.messageId !== "string" || !sent.messageId) {
        return response(409, { error: "provider_outcome_unknown", provider_code: "MESSAGE_ID_MISSING", provider_hint: "message_id_missing" });
      }
      return response(200, { accepted: true, message_id: sent.messageId });
    } catch (error) {
      return sendFailure(error);
    }
  },
};
