const CACHE_TTL_MS = 300_000;
let lastSuccessfulKey = '';
let lastSuccessfulAt = 0;

export function agentModelKey(model, session) {
  return `${model.id}\u0000${model.version || 0}\u0000${session?.csrfToken || ''}\u0000${session?.invalidationEpoch || 0}`;
}

export function clearAgentModelReady() { lastSuccessfulKey = ''; lastSuccessfulAt = 0; }

function keyFor(userId, modelId) {
  return `${userId}\u0000${modelId}`;
}

export function rememberAgentModelReady(userId, modelId, now = Date.now()) {
  lastSuccessfulKey = keyFor(userId, modelId);
  lastSuccessfulAt = now;
}

export function agentModelWasRecentlyReady(userId, modelId, now = Date.now()) {
  return keyFor(userId, modelId) === lastSuccessfulKey
    && now - lastSuccessfulAt >= 0
    && now - lastSuccessfulAt < CACHE_TTL_MS;
}
