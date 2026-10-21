const messages = {
  provider_not_configured: '尚未配置 AI 模型，请先完成模型设置。',
  provider_api_key_required: '当前模型缺少 API Key，请前往模型设置补充密钥。',
  provider_access_denied: '当前密钥没有访问权限，请检查服务商授权。',
  provider_auth_failed: '认证失败或当前密钥没有访问权限，请检查 API Key 和服务商授权。',
  provider_payment_required: '服务商账户余额不足或需要处理计费状态，请检查账户额度后重试。',
  provider_model_or_endpoint_not_found: '模型或接口地址不存在，请检查模型名称和兼容接口地址。',
  provider_rate_limited: '服务商请求过于频繁，请稍后再测试或生成。',
  provider_response_invalid: '模型返回的响应不符合兼容接口要求，请检查接口或更换模型。',
  provider_output_truncated: '模型回复达到输出上限，内容未完成。请简化描述或更换模型后重试。',
  provider_models_response_invalid: '服务商返回的模型列表无法识别。',
  provider_model_discovery_unavailable: '当前服务商未提供兼容的模型列表接口，请手动填写模型名称。',
  provider_dns_resolution_failed: '无法解析服务商域名，请检查接口地址或 DNS 设置。',
  provider_tls_verification_failed: 'HTTPS 证书校验失败，请检查服务商域名、证书和系统时间。',
  provider_tls_failed: 'HTTPS 安全连接失败，请检查服务商证书和 TLS 配置。',
  provider_server_error: '服务商暂时发生错误，请稍后重试。',
  provider_request_rejected: '服务商拒绝了请求，请检查接口地址、认证方式和账户权限。',
  invalid_model_proposal: '连接正常，但模型没有按要求的格式返回复核结果，请更换模型或调整配置。',
  provider_timeout: '连接超时，请检查服务地址和网络后重试。',
  provider_dns_timeout: '连接超时，请检查服务地址和网络后重试。',
  provider_unavailable: '暂时无法连接服务商，请检查网络和服务状态。',
  provider_address_rejected: '服务地址未通过安全校验，请使用可信的 HTTPS 公网接口地址。',
  provider_redirect_rejected: '服务地址发生重定向，请配置最终的 HTTPS 公网接口地址。',
  provider_response_too_large: '模型响应过大，请更换模型或稍后重试。',
  invalid_provider_config: '模型配置无效，请检查地址和模型名称。',
  ai_call_in_progress: '已有模型调用正在进行，请等待完成后再试（包括其他标签页）。',
  ai_call_rate_limited: '模型调用过于频繁，请稍后再试。',
  planning_context_limit: '对话内容已达到长度上限，请重新开始并简化描述。',
  planning_scope_required: '请先在“查询场地”读取当前 Token 的预约类别，再重新整理队列。',
  invalid_planning_request: '对话格式或轮数超出限制，最多支持原始描述和 20 次补充。',
};
export function providerErrorMessage(code) {
  const aliases = {access_denied:'provider_auth_failed',model_or_endpoint_not_found:'provider_model_or_endpoint_not_found',rate_limited:'provider_rate_limited'};
  const safeCode = typeof code === 'string' && /^[a-z0-9][a-z0-9_-]{0,63}$/i.test(code) ? code : '';
  return messages[aliases[code] || code] || (safeCode
    ? `服务端返回错误码 ${safeCode}，请检查配置后重试。`
    : '模型请求失败，请检查地址、模型名称和密钥后重试。');
}

export function providerDiscoveryErrorMessage(error) {
  if (error?.code) return providerErrorMessage(error.code);
  if (error?.kind === 'timeout') return '连接预约工作台超时，请确认本地服务仍在运行后重试。';
  if (error?.kind === 'network') return '浏览器无法连接预约工作台服务；请确认后端仍在运行，再重新读取模型列表。';
  if (Number.isInteger(error?.status) && error.status > 0) {
    return `预约工作台返回 HTTP ${error.status}，但没有提供错误码；请重新读取模型配置后重试。`;
  }
  return '模型列表请求没有返回可识别的错误信息；请确认预约工作台运行正常后重试。';
}
