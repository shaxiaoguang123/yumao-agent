// Lifecycle of one drafting conversation. Pure: transition(state, event) never mutates.
// Events that are not legal in a state are ignored, so the UI cannot reach a bad combination.

export const STATES = Object.freeze([
  'idle', 'generating', 'needs_input', 'ready', 'saving', 'saved', 'unsupported', 'escalated', 'error',
]);
export const EVENTS = Object.freeze([
  'SEND', 'ANSWER_NEEDS_INPUT', 'ANSWER_READY', 'ANSWER_UNSUPPORTED', 'ANSWER_ESCALATED', 'FAIL',
  'INPUT_CHANGED', 'CANCEL', 'RESTART', 'SAVE', 'SAVE_OK', 'SAVE_REJECTED', 'SAVE_CONFLICT', 'CONFLICT',
]);

export function initialState() {
  return { name: 'idle', stale: false, errorCode: '', conversation: null };
}

const move = (state, name, patch = {}) => ({ ...state, name, ...patch });
const reset = () => initialState();
const stale = (s) => ({ ...s, stale: true });
const answer = (name) => (s, e) => move(s, name, { conversation: e.conversation ?? null });
const send = (s) => move(s, 'generating', { errorCode: '', stale: false });

// A plan changing underneath an open draft marks it stale; it never ends the conversation.
const TABLE = {
  idle: {
    SEND: send,
    RESTART: reset,
    CONFLICT: stale,
  },
  generating: {
    ANSWER_NEEDS_INPUT: answer('needs_input'),
    ANSWER_READY: answer('ready'),
    ANSWER_UNSUPPORTED: answer('unsupported'),
    ANSWER_ESCALATED: answer('escalated'),
    FAIL: (s, e) => move(s, 'error', { errorCode: e.code ?? '' }),
    INPUT_CHANGED: reset,
    RESTART: reset,
    CONFLICT: stale,
  },
  needs_input: {
    SEND: send,
    INPUT_CHANGED: reset,
    CANCEL: reset,
    RESTART: reset,
    CONFLICT: stale,
  },
  ready: {
    SEND: send, // regenerate, e.g. after reading the latest plan
    SAVE: (s) => (s.stale ? s : move(s, 'saving')),
    INPUT_CHANGED: reset,
    CANCEL: reset,
    RESTART: reset,
    CONFLICT: stale,
  },
  saving: {
    SAVE_OK: (s) => move(s, 'saved', { stale: false, conversation: null }),
    SAVE_REJECTED: (s, e) => move(s, 'ready', { errorCode: e.code ?? '' }),
    SAVE_CONFLICT: (s) => move(s, 'ready', { stale: true, errorCode: 'plan_version_conflict' }),
  },
  saved: {
    SEND: send,
    INPUT_CHANGED: reset,
    RESTART: reset,
  },
  unsupported: {
    SEND: send,
    INPUT_CHANGED: reset,
    CANCEL: reset,
    RESTART: reset,
  },
  escalated: {
    INPUT_CHANGED: reset,
    CANCEL: reset,
    RESTART: reset,
  },
  error: {
    SEND: send,
    INPUT_CHANGED: reset,
    CANCEL: reset,
    RESTART: reset,
    CONFLICT: stale,
  },
};

export function transition(state, event) {
  const handler = TABLE[state.name]?.[event.type];
  return handler ? handler(state, event) : state;
}

export function isLegal(stateName, eventType) {
  return Boolean(TABLE[stateName]?.[eventType]);
}

// Status strings the existing child components already understand.
export function legacyStatus(state) {
  switch (state.name) {
    case 'saving':
      return 'ready';
    case 'escalated':
      return 'needs_input';
    default:
      return state.name;
  }
}

export const selectors = {
  busy: (s) => s.name === 'generating' || s.name === 'saving',
  saving: (s) => s.name === 'saving',
  escalated: (s) => s.name === 'escalated',
  stale: (s) => s.stale,
  composerLocked: (s) => s.name === 'saving' || s.name === 'escalated',
  canSave: (s) => s.name === 'ready' && !s.stale,
  followUp: (s) => s.name === 'needs_input',
  terminal: (s) => ['saved', 'unsupported', 'escalated'].includes(s.name),
};
