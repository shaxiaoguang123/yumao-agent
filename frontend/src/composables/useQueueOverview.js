import { onMounted, onUnmounted, reactive, ref, watch } from 'vue';

export function useQueueOverview(api, session, selection) {
  const queues = ref([]), counts = ref(null), total = ref(0), nextPage = ref(null);
  const status = ref('idle'), message = ref('');
  let alive = true, sequence = 0, controller, timer;
  const authorized = () => session?.status === 'authenticated' && Boolean(session?.user?.user_id);
  function cancel() { sequence++; controller?.abort(); clearTimeout(timer); }
  function schedule() {
    clearTimeout(timer);
    const selected = selection();
    if (selected.active && document.visibilityState !== 'hidden' && selected.category === 'pending'
      && queues.value.some(queue => ['running', 'ready', 'calibrated'].includes(queue.lifecycle.state)
        || Math.abs(queue.lifecycle.opening_at_utc_ms - Date.now()) < 60000)) timer = setTimeout(() => load(), 15000);
  }
  async function load(more = false) {
    if (more && (status.value === 'loading' || !nextPage.value)) return;
    cancel();
    const request = sequence, selected = { ...selection() }, user = session?.user?.user_id;
    if (!alive || !authorized() || !selected.credentialId || !selected.active) {
      queues.value = []; counts.value = null; nextPage.value = null; total.value = 0; status.value = 'idle'; message.value = ''; return;
    }
    const page = more ? nextPage.value : 1;
    if (!more) nextPage.value = null;
    status.value = 'loading'; message.value = '';
    controller = new AbortController();
    try {
      const result = await api.queueOverview(selected.credentialId, {
        category: selected.category, target_date: selected.targetDate || undefined, page, limit: 20,
      }, { signal: controller.signal });
      if (!alive || request !== sequence || user !== session?.user?.user_id || !authorized()) return;
      if (!Array.isArray(result?.queues) || !result.counts || (!Number.isSafeInteger(result.total) || result.total < 0) || result.page !== page
        || !(result.next_page === null || Number.isSafeInteger(result.next_page) && result.next_page === page + 1)
        || !['pending', 'succeeded', 'attention', 'all'].every(key => Number.isSafeInteger(result.counts[key]) && result.counts[key] >= 0)
        || result.queues.some(queue => !queue.record_id || !Array.isArray(queue.candidates) || !queue.lifecycle
          || !['pending', 'succeeded', 'attention'].includes(queue.lifecycle.category))) throw new Error('invalid_overview');
      queues.value = more ? [...new Map([...queues.value, ...result.queues].map(queue => [queue.record_id, queue])).values()] : result.queues;
      counts.value = result.counts; total.value = result.total; nextPage.value = result.next_page;
      status.value = 'ready'; schedule();
    } catch {
      if (!alive || request !== sequence || user !== session?.user?.user_id || !authorized()) return;
      if (!more) { queues.value = []; counts.value = null; total.value = 0; }
      status.value = 'error'; message.value = '计划与执行状态读取失败，请重试；当前不能判断是否成功或失败。';
    }
  }
  watch(() => [selection().credentialId, selection().category, selection().targetDate, selection().active,
    selection().refreshKey, session?.status, session?.user?.user_id, session?.csrfToken, session?.invalidationEpoch], () => {
    queues.value = []; counts.value = null; total.value = 0; void load();
  }, { immediate: true, flush: 'sync' });
  function visible() { if (document.visibilityState === 'hidden') clearTimeout(timer); else if (selection().active) void load(); }
  onMounted(() => document.addEventListener('visibilitychange', visible));
  onUnmounted(() => { alive = false; cancel(); document.removeEventListener('visibilitychange', visible); });
  return reactive({ queues, counts, total, nextPage, status, message, refresh: () => load(), more: () => load(true) });
}
