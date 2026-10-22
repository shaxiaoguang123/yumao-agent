export const logModules = [
  ['api', '接口请求'], ['auth', '登录与会话'], ['admin', '管理员操作'], ['credential', '预约凭据'],
  ['upstream', '上游请求'], ['agent', 'Agent'], ['execution', '预约执行'], ['system', '服务运行'],
];
export const logLevels = { info: '信息', warning: '警告', error: '错误' };
const labels = {
  'api.request': '接口请求', 'api.unhandled': '程序异常', 'service.started': '服务启动',
  'agent.turn': '对话处理', 'agent.model_call': '模型调用', 'agent.interpretation_rejected': '模型理解未通过校验',
  'agent.review_rejected': '预览复核未通过校验', 'upstream.request': '上游请求', 'upstream.transport_error': '上游连接异常',
  'execution.snapshot': '生成执行快照', 'execution.stage': '执行阶段', 'execution.finished': '执行结束',
  'execution.internal_error': '执行器内部异常', 'scheduler.settings_failed': '读取执行设置失败',
  'scheduler.queue_failed': '读取队列失败', 'scheduler.token_failed': '单个凭据执行异常',
  'scheduler.wait_settings_failed': '读取下次执行设置失败', 'scheduler.wait_queue_failed': '读取下次队列失败',
  'admin.logs_read': '查看日志列表', 'admin.log_detail_read': '查看日志详情', 'admin.metrics_read': '查看全站指标',
  'worker.stopped': '调度器意外退出',
  'credential.created': '添加预约凭据', 'credential.operation': '凭据操作',
  'admin.invitation_created': '创建邀请码', 'admin.user_disabled': '停用用户', 'admin.user_enabled': '启用用户',
};
export const actionLabel = action => labels[action] || action;
export const moduleLabel = module => logModules.find(item => item[0] === module)?.[1] || module;
export const logTime = value => value ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(value) : '—';
