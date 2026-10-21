import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue';

const SAFE_STATES = new Set([
  'observed_clear_unmarked',
  'observed_reserved',
  'observed_activity_occupied',
  'observed_unbookable',
  'observed_unknown',
]);

const ERROR_MESSAGES = {
  live_availability_disabled: '真实只读读取只在明确启用的本地开发环境提供。',
  credential_requires_validation: '请先在凭据页面重新验证预约凭据。',
  credential_unavailable: '所选预约凭据当前不可用。',
  credential_account_unverified: '凭据账户关联尚未确认，暂不能查询。',
  upstream_rate_limited: '读取频率已达到服务端限制，请等待后重试。',
  booking_window_closed: '此日期当前不在服务端允许的查询窗口内。',
  live_query_scope_expired: '查询类别引用已过期，请重新读取类别列表。',
  upstream_read_not_configured: '服务端尚未配置只读查询限制。',
  credential_changed: '凭据版本已变化，请重新读取类别列表。',
};

const DISABLED_MESSAGES = {
  feature_disabled: '服务端尚未启用真实只读场地查询。预约凭据仍已保存；此状态不会发起上游请求。',
  request_cipher_missing: '服务端尚未配置官方查询加密参数。预约凭据仍已保存；请先完成服务端配置。',
};

function validateGrid(value, targetDate, selectedLabel) {
  if (value?.grid_version !== 'official-bookingByTime-live-observation-v1'
      || value?.data_state !== 'live_observed_unverified'
      || value?.simulation !== false
      || value?.target_date !== targetDate
      || value?.query_scope?.display_name !== selectedLabel
      || value?.query_scope?.physical_venue_verified !== false
      || value?.can_select !== false || value?.can_match !== false
      || value?.can_book !== false || value?.can_pay !== false
      || value?.can_create_job !== false
      || value?.source?.data_state !== 'live_observed_unverified'
      || value?.source?.trust_state !== 'display_only_unverified'
      || value?.source?.price_state !== 'displayed_unit_unverified'
      || value?.can_bind !== false
      || !Number.isSafeInteger(value?.source?.captured_at_utc_ms)
      || !Number.isSafeInteger(value?.source?.ui_stale_after_utc_ms)
      || value.source.ui_stale_after_utc_ms <= value.source.captured_at_utc_ms
      || value.source.ui_stale_after_utc_ms - value.source.captured_at_utc_ms > 60000) return false;
  if (!Array.isArray(value.courts) || value.courts.length < 1 || value.courts.length > 32
      || !Array.isArray(value.rows) || !value.rows.length || value.rows.length > 48) return false;
  return value.rows.every((row) => Array.isArray(row.cells)
    && row.cells.length === value.courts.length
    && row.cells.every((cell) => SAFE_STATES.has(cell.state) && cell.selectable === false
      && (cell.price_display === null
        || (typeof cell.price_display === 'string' && /^[0-9]{1,12}$/.test(cell.price_display)))
      && (cell.intent_selectable !== true || (cell.state === 'observed_clear_unmarked' && value.client_selection_window === 'open'
        && value.can_select_intent === true && typeof row.intent_start_time==='string' && typeof row.intent_end_time==='string'
        && row.intent_start_time < row.intent_end_time))));
}

export function useLiveAvailability({ api, credentialApi, session, targetDate, contextKey }) {
  const enabled = ref(false);
  const autoLoading = ref(false);
  let readInterval = 0, nextReadAt = 0, refreshTimer = null, running = false, pending = false, reloadPending = false, scopeRenewals = 0, rateRetries = 0;
  const optionsLoading = ref(true);
  const optionsError = ref('');
  const disabledMessage = ref('');
  const credentials = ref([]);
  const credentialsError = ref('');
  const selectedCredentialId = ref('');
  const categories = ref([]);
  const selectedScopeReference = ref('');
  const categoriesLoading = ref(false);
  const gridLoading = ref(false);
  const grid = shallowRef(null);
  const gridExpired = ref(false);
  const error = ref('');
  const message = ref('');
  const eligibleCredentials = computed(() => credentials.value.filter((item) => (
    item.enabled === true
    && item.account_binding_state === 'confirmed'
    && item.requires_revalidation === false
    && item.last_confirmed_validation_state === 'confirmed_valid'
    && item.expiry_state !== 'expired'
  )));
  const selectedCategory = computed(() => categories.value.find(
    (item) => item.reference === selectedScopeReference.value,
  ) || null);

  let alive = true;
  let epoch = 0;
  let categorySequence = 0;
  let gridSequence = 0;
  let credentialSequence = 0;
  let expiryTimer = null;

  function clearGrid() {
    gridSequence += 1;
    grid.value = null;
    gridExpired.value = false;
    if (expiryTimer !== null) clearTimeout(expiryTimer);
    expiryTimer = null;
    error.value = '';
    message.value = '';
    gridLoading.value = false;
  }

  function clearPrivateState() {
    categorySequence += 1;
    credentialSequence += 1;
    selectedCredentialId.value = '';
    categories.value = [];
    selectedScopeReference.value = '';
    categoriesLoading.value = false;
    credentials.value = [];
    clearGrid();
  }

  function isAuthenticated() {
    return session()?.status === 'authenticated' && Boolean(session()?.user?.user_id);
  }

  async function initialize() {
    const requestEpoch = ++epoch;
    optionsLoading.value = true;
    optionsError.value = '';
    disabledMessage.value = '';
    credentialsError.value = '';
    clearPrivateState();
    if (!isAuthenticated()) {
      enabled.value = false;
      optionsLoading.value = false;
      return;
    }
    try {
      const result = await api.options();
      if (!alive || requestEpoch !== epoch) return;
      enabled.value = result?.enabled === true;
      if (!enabled.value) {
        disabledMessage.value = DISABLED_MESSAGES[result?.disabled_reason]
          || DISABLED_MESSAGES.feature_disabled;
      }
      readInterval = Number.isSafeInteger(result?.min_read_interval_ms) && result.min_read_interval_ms > 0 ? result.min_read_interval_ms : 0;
      if (!enabled.value) return;
      const credentialResult = await credentialApi.list();
      if (!alive || requestEpoch !== epoch) return;
      credentials.value = Array.isArray(credentialResult?.credentials)
        ? credentialResult.credentials
        : [];
      selectedCredentialId.value = eligibleCredentials.value[0]?.credential_id || '';
    } catch (requestError) {
      if (alive && requestEpoch === epoch) {
        if (requestError?.sessionInvalid) {
          optionsError.value = '登录状态已失效，请重新登录后再查询。';
          enabled.value = false;
        } else {
          optionsError.value = '只读查询能力读取失败，请检查本地服务后重试。';
        }
      }
    } finally {
      if (alive && requestEpoch === epoch) { optionsLoading.value = false; if(enabled.value && selectedCredentialId.value) refreshAvailability(); }
    }
  }

  async function refreshCredentials() {
    if (!isAuthenticated()) return;
    const requestEpoch = epoch;
    const sequence = ++credentialSequence;
    credentialsError.value = '';
    try {
      const result = await credentialApi.list();
      if (!alive || requestEpoch !== epoch || sequence !== credentialSequence) return;
      credentials.value = Array.isArray(result?.credentials) ? result.credentials : [];
      if (!eligibleCredentials.value.some((item) => item.credential_id === selectedCredentialId.value)) {
        selectedCredentialId.value = eligibleCredentials.value[0]?.credential_id || '';
      }
    } catch (requestError) {
      if (alive && requestEpoch === epoch && sequence === credentialSequence) credentialsError.value = requestError?.sessionInvalid
        ? '登录状态已失效，请重新登录后再查询。'
        : '预约凭据列表读取失败，请重试。';
    }
  }

  async function loadCategories() {
    clearGrid();
    categories.value = [];
    selectedScopeReference.value = '';
    if (!enabled.value || !selectedCredentialId.value || !eligibleCredentials.value.some(
      (item) => item.credential_id === selectedCredentialId.value,
    )) {
      error.value = '请先选择已启用且验证通过的预约凭据。';
      return;
    }
    const requestEpoch = epoch;
    const sequence = ++categorySequence;
    categoriesLoading.value = true;
    error.value = '';
    try {
      const result = await api.categories(selectedCredentialId.value);
      if (!alive || requestEpoch !== epoch || sequence !== categorySequence) return;
      if (result?.data_state !== 'live_observed_unverified'
          || result?.source !== 'official_read_only'
          || !Array.isArray(result?.options)
          || result.options.some((item) => typeof item?.reference !== 'string'
            || typeof item?.label !== 'string' || item.physical_venue_verified !== false)) {
        error.value = '服务端返回的类别数据格式未通过检查。';
        return;
      }
      categories.value = result.options;
      const badminton = result.options.filter(item => item.label === '羽毛球');
      if(badminton.length !== 1){ error.value='官方目录未返回唯一的羽毛球选项，请刷新场地。'; return; }
      selectedScopeReference.value = badminton[0].reference;
      message.value = result.notice || '官方预约类别已读取。';
    } catch (requestError) {
      if (alive && requestEpoch === epoch && sequence === categorySequence) {
        scheduleRateRetry(requestError);
        error.value = ERROR_MESSAGES[requestError?.code]
          || (requestError?.sessionInvalid
            ? '登录状态已失效，请重新登录后再查询。'
            : '类别读取失败；未使用缓存响应，请稍后重试。');
      }
    } finally {
      if (alive && requestEpoch === epoch && sequence === categorySequence) categoriesLoading.value = false;
      nextReadAt = Math.max(nextReadAt, Date.now() + readInterval);
    }
  }

  async function queryGrid() {
    clearGrid();
    if (!enabled.value || !selectedCredentialId.value || !selectedScopeReference.value || !targetDate()) {
      error.value = '请先选择预约凭据、查询类别和计划日期。';
      return;
    }
    const requestEpoch = epoch;
    const sequence = ++gridSequence;
    const requestedDate = targetDate();
    const scope = selectedCategory.value;
    if (!scope) { error.value = '查询类别已失效，请重新读取。'; return; }
    gridLoading.value = true;
    error.value = '';
    try {
      const result = await api.grid({
        credentialId: selectedCredentialId.value,
        scopeReference: scope.reference,
        targetDate: requestedDate,
      });
      if (!alive || requestEpoch !== epoch || sequence !== gridSequence
          || targetDate() !== requestedDate) return;
      if (!validateGrid(result, requestedDate, scope.label)) {
        error.value = '当前观察数据格式或来源标记无效，已停止展示。';
        return;
      }
      grid.value = result;
      gridExpired.value = false;
      expiryTimer = setTimeout(() => {
        if (alive && grid.value === result) gridExpired.value = true;
      }, Math.max(0, result.source.ui_stale_after_utc_ms - Date.now()));
      message.value = '';
    } catch (requestError) {
      if (alive && requestEpoch === epoch && sequence === gridSequence) {
        scheduleRateRetry(requestError);
        if(requestError?.code==='live_query_scope_expired'){categories.value=[];selectedScopeReference.value='';if(scopeRenewals<1){scopeRenewals++;pending=true;}}

        error.value = ERROR_MESSAGES[requestError?.code]
          || (requestError?.sessionInvalid
            ? '登录状态已失效，请重新登录后再查询。'
            : '当前读取失败；没有回退到旧响应，请检查网络后重试。');
      }
    } finally {
      if (alive && requestEpoch === epoch && sequence === gridSequence) gridLoading.value = false;
      nextReadAt = Math.max(nextReadAt, Date.now() + readInterval);
    }
  }

  function scheduleRateRetry(requestError){
    const delay=requestError?.retryAfterSeconds;
    if(requestError?.code==='upstream_rate_limited' && Number.isSafeInteger(delay) && delay>0 && delay<=900 && rateRetries<1){
      rateRetries++;nextReadAt=Math.max(nextReadAt,Date.now()+delay*1000);pending=true;
    }
  }
  function refreshAvailability({ reload = false } = {}) {
    if(!alive || !isAuthenticated() || !enabled.value || !selectedCredentialId.value || !targetDate())return;
    pending = true; reloadPending ||= reload; scopeRenewals=0; rateRetries=0; autoLoading.value = true;
    if(refreshTimer !== null){clearTimeout(refreshTimer);refreshTimer=null;}
    drainRefresh();
  }
  function drainRefresh(){
    if(!pending || running || !alive || !isAuthenticated())return;
    refreshTimer=setTimeout(async()=>{
      refreshTimer=null;
      if(!alive || !isAuthenticated() || !enabled.value || !targetDate()) {pending=false;autoLoading.value=false;return;}
      pending=false;running=true;
      try {
        if(reloadPending || !selectedScopeReference.value){
          reloadPending=false;
          await loadCategories();
          // Category read and slot read share a gate. One delayed continuation,
          // never polling; the next date selected wins while the read is pending.
          if(selectedScopeReference.value && !error.value)pending=true;
        }else await queryGrid();
      }finally{
        running=false;
        if(alive && pending)drainRefresh();else autoLoading.value=false;
      }
    },Math.max(0,nextReadAt-Date.now()));
  }
  function cancelRefresh(){
    pending=false;reloadPending=false;autoLoading.value=false;
    if(refreshTimer!==null)clearTimeout(refreshTimer);refreshTimer=null;
  }

  function invalidateForContext() {
    ++epoch;
    cancelRefresh();
    clearPrivateState();
    if (isAuthenticated()) void initialize();
  }

  watch(() => targetDate(), (next, previous) => {
    if(next!==previous){clearGrid();if(next)refreshAvailability();else cancelRefresh();}
  }, { flush: 'sync' });

  watch(selectedCredentialId, () => {
    categorySequence += 1;
    categories.value = [];
    selectedScopeReference.value = '';
    categoriesLoading.value = false;
    clearGrid();
    if(!optionsLoading.value)refreshAvailability();
  }, { flush: 'sync' });
  watch(selectedScopeReference, clearGrid, { flush: 'sync' });

  watch(() => [session()?.status, session()?.user?.user_id, session()?.csrfToken,
    session()?.invalidationEpoch], (next, previous) => {
    if (!previous) return;
    if (JSON.stringify(next) !== JSON.stringify(previous)) invalidateForContext();
  }, { flush: 'sync' });

  onMounted(() => void initialize());
  onBeforeUnmount(() => {
    alive = false;
    cancelRefresh();
    epoch += 1;
    categorySequence += 1;
    gridSequence += 1;
    if (expiryTimer !== null) clearTimeout(expiryTimer);
  });

  return {
    enabled, autoLoading, refreshAvailability, optionsLoading, optionsError, disabledMessage, credentials, credentialsError,
    eligibleCredentials, selectedCredentialId, categories, selectedScopeReference,
    selectedCategory, categoriesLoading, gridLoading, grid, gridExpired,
    error, message, initialize, refreshCredentials, loadCategories, queryGrid,
    clearGrid,
  };
}
