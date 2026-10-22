export function createOrderApi(client) {
  if (typeof client?.request !== 'function') throw new TypeError('an authenticated HTTP client is required');
  return {
    query: ({ credentialId, page = 1, pageSize = 10, status = '' }) => client.request('/api/orders/query', {
      method: 'POST', body: { credential_id: credentialId, page, page_size: pageSize, status },
    }),
    details: ({ credentialId, reference }) => client.request('/api/orders/details', {
      method: 'POST', body: { credential_id: credentialId, reference },
    }),
  };
}

export function orderErrorMessage(error) {
  return ({
    order_query_rate_limited: '订单查询过于频繁，请稍后重试。',
    upstream_read_rate_limited: '订单查询过于频繁，请稍后重试。',
    order_reference_expired: '订单信息已过期，请刷新列表后重新打开。',
    order_not_found: '这条订单暂时无法读取，请刷新列表后重试。',
    credential_not_found: '当前凭据已不存在，请重新选择 Token。',
    credential_token_expired: '当前 Token 已过期，请前往预约凭据更新。',
    credential_token_invalid: '当前 Token 已失效，请前往预约凭据更新。',
    credential_disabled: '当前 Token 已停用，请前往预约凭据检查。',
    credential_requires_revalidation: '当前 Token 需要重新验证，请前往预约凭据检查。',
    credential_account_binding_unresolved: '当前 Token 尚未确认账户，请先验证凭据。',
    credential_account_reconfirmation_required: '当前 Token 需要重新确认账户，请检查凭据。',
    order_upstream_authentication_failed: '官方暂未接受当前 Token，请验证凭据后重试。',
    order_response_invalid: '官方订单数据格式发生变化，请稍后重试。',
    order_query_unavailable: '服务端尚未配置订单查询，请联系管理员。',
    order_query_rejected: '官方暂未接受本次订单查询，请稍后重试。',
  })[error?.code] || '订单读取失败，请检查网络后重试。';
}
