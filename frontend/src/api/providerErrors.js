const messages = {
  provider_not_configured: '尚未配置 AI 模型，请先完成模型设置。',
  provider_api_key_required: '当前模型缺少 API Key，请前往模型设置补充密钥。',
  provider_access_denied: '当前密钥没有访问权限，请检查服务商授权。',
  provider_auth_failed: '认证失败或当前密钥没有访问权限，请检查 API Key 和服务商授权。',
  provider_model_or_endpoint_not_found: '模型或接口地址不存在，请检查模型名称和兼容接口地址。',
  provider_rate_limited: '服务商请求过于频繁，请稍后再测试或生成。',
  provider_response_invalid: '模型返回的响应不符合兼容接口要求，请检查接口或更换模型。',
  invalid_model_proposal: '连接正常，但模型返回的计划结构或字段依据不符合要求，请更换模型或调整配置。',
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
  invalid_planning_request: '对话格式或轮数超出限制，最多支持原始描述和 7 次补充。',
};
export function providerErrorMessage(code) {
  const aliases = {access_denied:'provider_auth_failed',model_or_endpoint_not_found:'provider_model_or_endpoint_not_found',rate_limited:'provider_rate_limited'};
  return messages[aliases[code] || code] || '模型请求失败，请检查地址、模型名称和密钥后重试。';
}
