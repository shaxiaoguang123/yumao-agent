<script setup>
import { onUnmounted, ref, watch } from 'vue';
import AppIcon from '../AppIcon.vue';

const props = defineProps({
  api: { type: Object, required: true },
  session: { type: Object, required: true },
});

const successes = ref([]);
const workerEnabled = ref(false);
const state = ref('loading');
let alive = true;
let sequence = 0;

function dateTime(value) {
  if (!Number.isSafeInteger(value)) return '—';
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(value);
}

async function load() {
  const current = ++sequence;
  state.value = 'loading';
  try {
    const result = await props.api.executionSuccesses();
    if (!alive || current !== sequence) return;
    if (!Array.isArray(result?.successes)
        || typeof result.worker_enabled !== 'boolean'
        || result.successes.some(item => (
          item?.verification !== 'order_query'
          || typeof item.credential_id !== 'string'
          || typeof item.target_date !== 'string'
          || !Number.isSafeInteger(item.confirmed_at_utc_ms)
        ))) throw new Error('invalid_response');
    successes.value = result.successes;
    workerEnabled.value = result.worker_enabled;
    state.value = 'ready';
  } catch {
    if (!alive || current !== sequence) return;
    state.value = 'error';
  }
}

watch(() => [
  props.session?.status,
  props.session?.user?.user_id,
  props.session?.invalidationEpoch,
], () => {
  if (props.session?.status === 'authenticated') void load();
  else {
    sequence += 1;
    successes.value = [];
    state.value = 'idle';
  }
}, { immediate: true, flush: 'sync' });

onUnmounted(() => { alive = false; sequence += 1; });
</script>

<template>
  <section class="booking-success-panel" aria-labelledby="booking-success-title">
    <header class="booking-success-heading">
      <div>
        <p class="eyebrow">订单查询确认</p>
        <h2 id="booking-success-title">抢票结果</h2>
      </div>
      <button class="text-button" type="button" :disabled="state === 'loading'" @click="load">
        刷新
      </button>
    </header>

    <p v-if="state === 'loading'" class="muted" role="status">正在读取已确认订单…</p>
    <p v-else-if="state === 'error'" class="form-error" role="alert">
      抢票结果读取失败。<button class="text-button" type="button" @click="load">重新读取</button>
    </p>
    <div v-else-if="successes.length" class="booking-success-list">
      <article v-for="item in successes" :key="item.run_id" class="booking-success-card">
        <span class="booking-success-mark"><AppIcon name="check" /></span>
        <div class="booking-success-main">
          <div class="booking-success-title-line">
            <strong>预约成功</strong>
            <span>{{ item.credential_label }}</span>
          </div>
          <p>{{ item.target_date }} · {{ item.start_time }}–{{ item.end_time }} · {{ item.court_preference }}</p>
          <small>{{ item.scope_label || '预约场地' }} · {{ item.duration_minutes }} 分钟 · {{ dateTime(item.confirmed_at_utc_ms) }} 查单确认</small>
        </div>
      </article>
    </div>
    <p v-else class="booking-success-empty">
      {{ workerEnabled ? '还没有经订单查询确认的成功记录。' : '执行器尚未启用，暂无自动抢票结果。' }}
    </p>
  </section>
</template>

<style scoped>
.booking-success-panel{display:grid;gap:12px;margin:0 0 16px;padding:16px;border:1px solid var(--line);border-radius:16px;background:var(--surface)}
.booking-success-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}.booking-success-heading .eyebrow{margin:0 0 2px;font-size:10px}.booking-success-heading h2{font-size:18px}
.booking-success-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:8px}
.booking-success-card{display:flex;align-items:flex-start;gap:12px;padding:14px;border:1px solid color-mix(in srgb,var(--success) 22%,transparent);border-radius:14px;background:var(--success-soft);min-width:0}
.booking-success-mark{display:grid;place-items:center;flex:0 0 40px;height:40px;border-radius:50%;background:var(--success-fill);color:var(--on-accent)}.booking-success-mark :deep(svg){width:22px;height:22px;stroke-width:2.4}
.booking-success-main{min-width:0}.booking-success-title-line{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.booking-success-title-line strong{color:var(--success);font-size:16px}.booking-success-title-line span{max-width:100%;padding:3px 8px;border-radius:999px;background:var(--surface);color:var(--muted);font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.booking-success-main p{margin:5px 0 2px;font-size:14px;font-weight:600;line-height:1.5}.booking-success-main small{display:block;color:var(--muted);font-size:11px;line-height:1.55}
.booking-success-empty{margin:0;padding:12px;border-radius:12px;background:var(--page);color:var(--muted);font-size:13px}
@media(max-width:560px){.booking-success-panel{padding:14px 12px}.booking-success-list{grid-template-columns:minmax(0,1fr)}.booking-success-card{padding:12px}.booking-success-heading .text-button{padding-inline:10px}}
</style>
