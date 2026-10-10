<script setup>
import AppIcon from './AppIcon.vue';
defineProps({ credential:{type:Object,required:true},busy:Boolean });
defineEmits(['validate','rotate','toggle','remove']);
const expiryLabels = {
  expiry_unknown: '到期时间未知',
  expiry_ok: '有效期正常',
  expiring_soon: '即将过期',
  expired: '已过期',
};
const validationLabels = {
  never_confirmed: '尚未确认',
  confirmed_valid: '已验证有效',
  confirmed_invalid: '已确认无效',
};
const bindingLabels = {
  unresolved: '尚未确认',
  confirmed: '已确认',
  needs_reconfirmation: '需要重新确认',
};
const attemptLabels = {
  success: '验证成功',
  explicit_invalid: 'Token 已确认无效',
  network_error: '网络错误',
  rate_limited: '受到限流',
  contract_drift: '上游协议变化',
  validation_unknown: '结果未知',
  unresolved_identity: 'Token 已验证，账户连续性未确认',
  internal_error: '验证暂不可用',
};
const operationLabels = {
  create_candidate: '添加 Token',
  validate_current: '验证当前 Token',
  token_rotation_candidate: '验证替换 Token',
};
function formatDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
}

function expiryText(value) {
  return expiryLabels[value] || '到期时间未知';
}

function validationText(value) {
  return validationLabels[value] || '验证状态未知';
}

function bindingText(value) {
  return bindingLabels[value] || '账户状态未知';
}

function attemptText(value) {
  return attemptLabels[value] || '验证结果未知';
}

</script><template>
      <article
        class="credential-card"
        :data-testid="`credential-card-${credential.credential_id}`"
      >
        <header class="credential-card-heading">
          <div class="credential-identity">
            <h3>{{ credential.label }}</h3>
            <p class="muted">版本 {{ credential.credential_version }}</p>
          </div>
          <span class="state-pill" :class="credential.enabled ? 'state-enabled' : 'state-disabled'">
            {{ credential.enabled ? '已启用' : '已停用' }}
          </span>
        </header>

        <dl class="credential-facts">
          <div>
            <dt>账户连续性</dt>
            <dd class="fact-state" :class="credential.account_binding_state === 'confirmed' ? 'fact-positive' : 'fact-warning'">{{ bindingText(credential.account_binding_state) }}</dd>
          </div>
          <div>
            <dt>Token 验证</dt>
            <dd class="fact-state" :class="credential.last_confirmed_validation_state === 'confirmed_valid' ? 'fact-positive' : 'fact-warning'">{{ validationText(credential.last_confirmed_validation_state) }}</dd>
          </div>
          <div>
            <dt>有效期</dt>
            <dd>{{ expiryText(credential.expiry_state) }}</dd>
          </div>
          <div>
            <dt>Token 到期时间</dt>
            <dd>{{ formatDate(credential.token_expires_at_utc) }}</dd>
          </div>
          <div>
            <dt>最近成功验证</dt>
            <dd>{{ formatDate(credential.last_successful_validation_at_utc) }}</dd>
          </div>

        </dl>
        <details class="validation-record"><summary><span><AppIcon name="clock" />验证记录</span><span class="record-result">{{ credential.latest_requested_validation_attempt ? attemptText(credential.latest_requested_validation_attempt.attempt_result) : '尚无记录' }}</span></summary><dl>          <div>
            <dt>最近发起的验证</dt>
            <dd v-if="credential.latest_requested_validation_attempt">
              {{ operationLabels[credential.latest_requested_validation_attempt.operation_kind] || '验证请求' }}：
              {{ attemptText(credential.latest_requested_validation_attempt.attempt_result) }}
              <span class="muted">
                （开始 {{ formatDate(credential.latest_requested_validation_attempt.started_at_utc) }}；
                完成 {{ formatDate(credential.latest_requested_validation_attempt.completed_at_utc) }}）
              </span>
            </dd>
            <dd v-else>尚无验证请求</dd>
          </div></dl></details>

        <p v-if="credential.expiry_state === 'expiring_soon'" class="risk-note">
          Token 即将到期，请提前准备替换 Token。此提醒本身不会阻止当前凭据使用。
        </p>
        <p v-if="credential.expiry_state === 'expired' || credential.last_confirmed_validation_state === 'confirmed_invalid'" class="risk-note danger-note">
          当前 Token 已过期或已确认无效，需验证新的 Token 后才能继续使用。
        </p>
        <p v-if="credential.requires_revalidation" class="risk-note">
          凭据重新启用后需要再次验证当前 Token。
        </p>
        <p v-if="credential.account_binding_state === 'unresolved'" class="risk-note">
          账户连续性尚未确认。此凭据不能轮换 Token，也不能用于依赖上游账户身份的后续预约任务；可重新验证当前 Token 以尝试确认。
        </p>
        <p v-if="credential.account_binding_state === 'needs_reconfirmation'" class="risk-note danger-note">
          账户连续性需要重新确认。轮换和后续账户级使用已暂停；验证当前 Token 并匹配原账户后才能恢复。
        </p>

        <div class="credential-actions">
          <button
            v-if="credential.enabled"
            class="secondary-button"
            type="button"
            :data-testid="`validate-${credential.credential_id}`"
            :disabled="busy"
            @click="$emit('validate')"
          >
            {{ busy ? '处理中…' : '验证当前 Token' }}
          </button>
          <button
            v-if="credential.enabled && credential.account_binding_state === 'confirmed'"
            class="secondary-button"
            type="button"
            :data-testid="`rotate-${credential.credential_id}`"
            :disabled="busy"
            @click="$emit('rotate')"
          >
            轮换 Token
          </button>
          <button
            class="secondary-button"
            type="button"
            :data-testid="`credential-${credential.enabled ? 'disable' : 'enable'}-${credential.credential_id}`"
            :disabled="busy"
            @click="$emit('toggle')"
          >
            {{ credential.enabled ? '停用' : '重新启用' }}
          </button>
          <button
            class="danger-button"
            type="button"
            :data-testid="`credential-delete-${credential.credential_id}`"
            :disabled="busy"
            @click="$emit('remove')"
          >
            删除
          </button>
        </div>

        <slot />

      </article>
</template>
<style scoped>
.credential-card {
  min-width:0;
  padding:24px;
  border:1px solid var(--line);
  border-radius:14px;
  background:var(--surface);

}

.credential-card-heading {
  display:flex;
  justify-content:space-between;
  align-items:flex-start;
  gap:16px;

}

.credential-identity {
  min-width:0;

}

.credential-card-heading h3 {
  margin:0;
  overflow-wrap:anywhere;
  font-weight:650;
  line-height:1.5;

}

.credential-card-heading p {
  margin:5px 0 0;
  font-size:10px;
  color:var(--muted);

}

.credential-facts {
  display:grid;
  grid-template-columns:repeat(3,minmax(0,1fr));
  gap:17px 22px;
  margin:22px 0;

}

.credential-facts > div {
  min-width:0;

}  .credential-facts dt {
  font-size:11px;
  color:var(--muted);

}

.credential-facts dd {
  margin:6px 0 0;
  font-size:12px;
  line-height:1.75;
  overflow-wrap:anywhere;

}

.credential-facts dd span {
  display:block;
  font-size:11px;

}

.risk-note {
  margin:10px 0;
  padding:11px 14px;
  border-left:2px solid #d0a557;
  border-radius:5px;
  background:var(--warning-soft);
  color:var(--warning);
  font-size:12px;
  line-height:1.8;

}

.danger-note {
  background:var(--danger-soft);
  color:var(--danger);
  border-left-color:var(--danger);

}

.credential-actions {
  display:flex;
  flex-wrap:wrap;
  gap:8px;
  padding-top:8px;

}

.credential-actions button {
  font-size:12px;
  padding:10px 12px;

}
@media(max-width:640px) {
  .credential-card {
  padding:20px;

}

.credential-facts {
  grid-template-columns:repeat(2,minmax(0,1fr));
  gap:16px;

}

.credential-facts > div:nth-child(3) {
  grid-column:1/-1;

}

.credential-actions button {
  font-size:12px;

}
}
.fact-state {
  font-weight:600;

}

.fact-positive {
  color:var(--brand);

}

.fact-warning {
  color:var(--warning);

}

.validation-record {
  border-top:1px solid var(--line);
  margin-bottom:10px;

}

.validation-record summary {
  display:flex;
  justify-content:space-between;
  align-items:center;
  gap:12px;
  min-height:44px;
  cursor:pointer;
  color:var(--muted);
  font-size:11px;
  list-style:none;

}

.validation-record summary:after {
  content:"+";
  font-size:17px;
  color:var(--brand);

}

.validation-record[open] summary:after {
  content:"−";

}

.validation-record summary > span:first-child {
  display:flex;
  align-items:center;
  gap:7px;

}

.validation-record summary svg {
  width:15px;
  height:15px;

}

.record-result {
  margin-left:auto;
  font-size:11px;

}

.validation-record dl {
  padding:12px 14px;
  margin:0 0 10px;
  background:var(--page);
  border-radius:8px;
  font-size:11px;
  line-height:1.7;

}

.validation-record dt {
  color:var(--muted);
  margin-bottom:6px;

}

.validation-record dd {
  margin:0;

}

.validation-record dd span {
  display:block;
  color:var(--muted);

}
</style>
