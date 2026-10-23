const INVALID_SESSION_CODES = new Set([
  'session_invalid',
  'session_expired',
  'session_revoked',
]);
const PUBLIC_MUTATIONS = new Set([
  '/api/auth/login',
  '/api/auth/register',
]);

export class HttpError extends Error {
  constructor(message, {
    status = 0,
    code = '',
    kind = 'http',
    fields = {},
    sessionInvalid = false,
    cause = undefined,
    retryAfterSeconds = null,
    requestId = '',
  } = {}) {
    super(message, { cause });
    this.name = 'HttpError';
    this.status = status;
    this.code = code;
    this.requestId = /^[a-f0-9]{32}$/.test(requestId) ? requestId : '';
    this.kind = kind;
    this.fields = fields;
    this.retryAfterSeconds = Number.isSafeInteger(retryAfterSeconds) && retryAfterSeconds > 0 && retryAfterSeconds <= 900 ? retryAfterSeconds : null;
    this.sessionInvalid = sessionInvalid || INVALID_SESSION_CODES.has(code);
  }
}

function responseCode(body) {
  return body && typeof body === 'object' && typeof body.error === 'string'
    ? body.error
    : '';
}

async function readBody(response) {
  if (response.status === 204) return null;
  try {
    return await response.json();
  } catch (error) {
    if (error?.name === 'AbortError' || error?.name === 'TimeoutError') throw error;
    return null;
  }
}

export function createHttpClient({
  fetchImpl = (...args) => globalThis.fetch(...args),
  getCsrfToken = () => '',
  onSessionInvalid = () => {},
} = {}) {
  async function request(path, options = {}) {
    const method = String(options.method || 'GET').toUpperCase();
    const headers = { ...(options.headers || {}) };
    let body = options.body;
    if (body !== undefined && body !== null && typeof body !== 'string') {
      body = JSON.stringify(body);
      if (!Object.keys(headers).some((name) => name.toLowerCase() === 'content-type')) {
        headers['Content-Type'] = 'application/json';
      }
    }

    const pathWithoutQuery = String(path).split(/[?#]/, 1)[0];
    const isMutation = !['GET', 'HEAD', 'OPTIONS'].includes(method);
    if (isMutation && !PUBLIC_MUTATIONS.has(pathWithoutQuery)) {
      const csrfToken = getCsrfToken();
      if (csrfToken) headers['X-CSRF-Token'] = csrfToken;
    }

    const { timeoutMs = isMutation ? 30_000 : 15_000, signal, ...requestOptions } = options;
    const controller = new AbortController();
    const cancel = () => controller.abort(signal.reason);
    const init = {
      ...requestOptions,
      method,
      credentials: 'include',
      headers,
      signal: controller.signal,
    };
    if (body === undefined) delete init.body;
    else init.body = body;

    let response, payload, rejectAbort;
    const abortPromise = new Promise((_, reject) => { rejectAbort = reject; });
    const onAbort = () => rejectAbort(controller.signal.reason || new DOMException('Request cancelled', 'AbortError'));
    controller.signal.addEventListener('abort', onAbort, { once: true });
    signal?.addEventListener('abort', cancel, { once: true });
    const timer = setTimeout(() => controller.abort(new DOMException('Request timed out', 'TimeoutError')), timeoutMs);
    try {
      if (signal?.aborted) cancel();
      [response, payload] = await Promise.race([
        controller.signal.aborted ? abortPromise : (async () => { const result = await fetchImpl(path, init); return [result, await readBody(result)]; })(),
        abortPromise,
      ]);
    } catch (cause) {
      const kind = controller.signal.aborted || cause?.name === 'AbortError' || cause?.name === 'TimeoutError'
        ? 'timeout'
        : 'network';
      throw new HttpError(
        kind === 'timeout' ? '请求超时，请重试' : '网络暂不可用，请重试',
        { kind, cause },
      );
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', cancel);
      controller.signal.removeEventListener('abort', onAbort);
    }

    if (!response.ok) {
      const code = responseCode(payload);
      const isPublicLoginFailure = pathWithoutQuery === '/api/auth/login'
        && code === 'invalid_credentials';
      const isSessionInvalid = INVALID_SESSION_CODES.has(code)
        || (response.status === 401
          && !isPublicLoginFailure
          && !PUBLIC_MUTATIONS.has(pathWithoutQuery));
      if (isSessionInvalid) onSessionInvalid();
      throw new HttpError(code || '请求失败', {
        status: response.status,
        code,
        kind: 'http',
        fields: payload?.fields || {},
        retryAfterSeconds: payload?.retry_after_seconds,
        sessionInvalid: isSessionInvalid,
        requestId: response.headers?.get?.('X-Request-ID') || '',
      });
    }
    return payload;
  }

  return { request };
}

export const httpClient = createHttpClient();
