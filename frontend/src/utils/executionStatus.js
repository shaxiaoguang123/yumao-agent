export const executionStateLabels = {
  ready: '已复核 · 等待 07:30',
  calibrated: '时间已校准 · 等待执行',
  running: '执行中',
  succeeded: '已执行 · 抢票成功',
  failed: '三轮未成功',
  empty: '复核后没有可执行候选',
  stale: '保存队列已变更',
  needs_attention: '需要关注',
};
