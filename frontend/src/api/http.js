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
    sessionInvalid = false,
    cause = undefined,
  } = {}) {
    super(message, { cause });
    this.name = 'HttpError';
    this.status = status;
    this.code = code;
    this.kind = kind;
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
  } catch {
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

    const init = {
      ...options,
      method,
      credentials: 'include',
      headers,
    };
    if (body === undefined) delete init.body;
    else init.body = body;

    let response;
    try {
      response = await fetchImpl(path, init);
    } catch (cause) {
      const kind = cause?.name === 'AbortError' || cause?.name === 'TimeoutError'
        ? 'timeout'
        : 'network';
      throw new HttpError(
        kind === 'timeout' ? '请求超时，请重试' : '网络暂不可用，请重试',
        { kind, cause },
      );
    }

    const payload = await readBody(response);
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
        sessionInvalid: isSessionInvalid,
      });
    }
    return payload;
  }

  return { request };
}

export const httpClient = createHttpClient();
