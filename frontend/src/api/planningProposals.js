export function createPlanningProposalApi(client) {
  if (typeof client?.request !== 'function') throw new TypeError('an authenticated HTTP client is required');
  const scopedPath=(path,credentialId)=>`${path}?${new URLSearchParams({credential_id:credentialId})}`;
  return {
    generate: ({message, credentialId, answers, askedFields, scopeLabel, conversationId, regenerate}) => client.request('/api/planning/queue-proposals', {
      method:'POST',
      body:{message,credential_id:credentialId,...(conversationId?{conversation_id:conversationId}:{}),...(answers?.length?{answers,asked_fields:askedFields}:{}),...(scopeLabel?{scope_label:scopeLabel}:{}),...(regenerate?{regenerate:true}:{})},
    }),
    restore: (credentialId,conversationId) => client.request(scopedPath(conversationId?`/api/planning/queue-conversations/${encodeURIComponent(conversationId)}`:'/api/planning/queue-conversations',credentialId)),
    resume: (conversationId,credentialId) => client.request(scopedPath(`/api/planning/queue-conversations/${encodeURIComponent(conversationId)}/resume`,credentialId),{method:'POST',body:{}}),
    close: (conversationId,credentialId,outcome) => client.request(scopedPath(`/api/planning/queue-conversations/${encodeURIComponent(conversationId)}/close`,credentialId),{method:'POST',body:outcome?{outcome}:{}}),
  };
}
