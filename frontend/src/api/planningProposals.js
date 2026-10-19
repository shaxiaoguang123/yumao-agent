export function createPlanningProposalApi(client) {
  if (typeof client?.request !== 'function') throw new TypeError('an authenticated HTTP client is required');
  const scopedPath=(path,credentialId)=>`${path}?${new URLSearchParams({credential_id:credentialId})}`;
  return {
    generate: ({message, credentialId, answers, askedFields, scopeLabel, conversationId}) => client.request('/api/planning/queue-proposals', {
      method:'POST',
      body:{message,credential_id:credentialId,...(conversationId?{conversation_id:conversationId}:{}),...(answers?.length?{answers,asked_fields:askedFields}:{}),...(scopeLabel?{scope_label:scopeLabel}:{})},
    }),
    restore: (credentialId) => client.request(scopedPath('/api/planning/queue-conversations',credentialId)),
    close: (conversationId,credentialId) => client.request(scopedPath(`/api/planning/queue-conversations/${encodeURIComponent(conversationId)}/close`,credentialId),{method:'POST',body:{}}),
  };
}
