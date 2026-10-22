<script setup>
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue';
import { RouterLink } from 'vue-router';
import ActivityOverview from '../components/metrics/ActivityOverview.vue';
import PageHeader from '../components/PageHeader.vue';

const api = inject('adminUsersApi');
const session = inject('sessionStore');
const users = ref([]);
const summary = ref(null);
const status = ref('idle');
const errorMessage = ref('');
const notice = ref('');
const search = ref('');
const statusFilter = ref('all');
const roleFilter = ref('all');
const offset = ref(0);
const total = ref(0);
const pageSize = 50;
const busyUserId = ref('');
const authorized = computed(() => session?.status === 'authenticated' && session.user?.role === 'admin');
const currentPage = computed(() => Math.floor(offset.value / pageSize) + 1);
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));
let alive = true;
let epoch = 0;
let requestId = 0;

function errorText(error) {
  if (error?.sessionInvalid || error?.status === 401) return '管理员登录状态已失效，请重新登录。';
  if (error?.status === 403) return '当前会话没有管理员权限。';
  if (error?.status === 400) return '筛选条件无效，请调整后重试。';
  if (error?.kind === 'network' || error?.kind === 'timeout') return '无法连接用户管理服务，请确认后端运行正常后重试。';
  return '用户数据读取失败，请重试。';
}

async function load(nextOffset = offset.value) {
  if (!authorized.value || !api || status.value === 'loading') return;
  const sequence = ++requestId;
  const generation = epoch;
  offset.value = nextOffset;
  status.value = 'loading';
  errorMessage.value = '';
  try {
    const result = await api.list({
      q: search.value,
      role: roleFilter.value,
      status: statusFilter.value,
      limit: pageSize,
      offset: offset.value,
    });
    if (!alive || generation !== epoch || sequence !== requestId) return;
    if (!Array.isArray(result?.users) || !Number.isSafeInteger(result.total)
        || !result.summary || !Number.isSafeInteger(result.summary.total)) {
      throw new Error('invalid_admin_user_response');
    }
    users.value = result.users;
    summary.value = result.summary;
    total.value = result.total;
    status.value = 'ready';
  } catch (error) {
    if (!alive || generation !== epoch || sequence !== requestId) return;
    errorMessage.value = errorText(error);
    status.value = 'error';
  }
}

function applyFilters() {
  return load(0);
}

async function setUserEnabled(user) {
  if (!authorized.value || busyUserId.value || !api) return;
  const enabling = user.status === 'disabled';
  if (!enabling && user.user_id === session.user.user_id) return;
  if (!enabling && user.role === 'admin' && summary.value?.active_admins <= 1) return;
  const action = enabling ? '重新启用' : '停用';
  if (!window.confirm(`确认${action}用户“${user.username}”吗？${enabling ? '' : '该用户的现有会话会被撤销。'}`)) return;

  busyUserId.value = user.user_id;
  errorMessage.value = '';
  notice.value = '';
  try {
    await api[enabling ? 'enable' : 'disable'](user.user_id);
    notice.value = `${user.username} 已${enabling ? '重新启用' : '停用'}。`;
    await load(offset.value);
  } catch (error) {
    errorMessage.value = error?.status === 409
      ? '该操作会影响管理员安全约束，请刷新后检查账户状态。'
      : errorText(error);
  } finally {
    if (alive) busyUserId.value = '';
  }
}

function formatCreatedAt(value) {
  if (!Number.isSafeInteger(value) || value <= 0) return '—';
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium' }).format(new Date(value));
}

watch(() => [session?.status, session?.user?.user_id, session?.user?.role], () => {
  epoch += 1;
  requestId += 1;
  users.value = [];
  summary.value = null;
  total.value = 0;
  busyUserId.value = '';
  errorMessage.value = '';
  notice.value = '';
  status.value = authorized.value ? 'idle' : 'error';
  if (authorized.value) void load(0);
}, { immediate: true, flush: 'sync' });

onBeforeUnmount(() => {
  alive = false;
  epoch += 1;
  requestId += 1;
});
</script>

<template>
  <section class="admin-users-page" aria-labelledby="admin-users-title">
    <PageHeader
      title-id="admin-users-title"
      eyebrow="管理员工作台"
      title="用户管理"
      description="查看账户状态，管理用户访问权限。"
    />

    <ActivityOverview v-if="authorized" system />

    <p v-if="!authorized" class="form-error" role="alert">管理员登录状态已失效，请重新登录。</p>
    <p v-if="errorMessage" class="form-error" role="alert">{{ errorMessage }} <button class="text-button" type="button" @click="load()">重试</button></p>
    <p v-if="notice" class="form-success" role="status">{{ notice }}</p>

    <section v-if="summary" class="admin-user-stats" aria-label="用户统计" :aria-busy="status === 'loading'">
      <article class="panel admin-stat"><span>账户总数</span><strong>{{ summary.total }}</strong><small>所有注册账户</small></article>
      <article class="panel admin-stat"><span>正常使用</span><strong>{{ summary.active }}</strong><small>当前可登录</small></article>
      <article class="panel admin-stat"><span>已停用</span><strong>{{ summary.disabled }}</strong><small>无法继续登录</small></article>
      <article class="panel admin-stat"><span>启用管理员</span><strong>{{ summary.active_admins }}</strong><small>保留至少一个管理员</small></article>
    </section>

    <section class="panel admin-user-panel" aria-labelledby="admin-user-list-title" :aria-busy="status === 'loading'">
      <div class="admin-user-heading">
        <div><h2 id="admin-user-list-title">账户列表</h2><p class="muted">列表不包含密码、Token 或 API 密钥。</p></div>
        <RouterLink class="secondary-button" :to="{ name: 'admin-invitations' }">管理邀请码</RouterLink>
      </div>

      <form class="admin-user-filters" role="search" @submit.prevent="applyFilters">
        <label class="field admin-user-search">搜索用户名<input v-model="search" type="search" maxlength="128" placeholder="输入用户名" /></label>
        <label class="field">账户状态<select v-model="statusFilter" @change="applyFilters"><option value="all">全部状态</option><option value="active">正常使用</option><option value="disabled">已停用</option></select></label>
        <label class="field">账户角色<select v-model="roleFilter" @change="applyFilters"><option value="all">全部角色</option><option value="admin">管理员</option><option value="user">用户</option></select></label>
        <button class="primary-button" type="submit" :disabled="status === 'loading'">搜索</button>
        <button class="secondary-button" type="button" :disabled="status === 'loading'" @click="load()">刷新</button>
      </form>

      <p v-if="status === 'loading'" class="muted" role="status">正在读取用户列表…</p>
      <p v-else-if="status === 'ready' && users.length === 0" class="admin-user-empty">没有符合条件的用户。</p>
      <div v-else-if="status === 'ready'" class="admin-user-table-scroll">
        <table class="admin-user-table">
          <thead><tr><th scope="col">用户名</th><th scope="col">角色</th><th scope="col">状态</th><th scope="col">创建时间</th><th scope="col">操作</th></tr></thead>
          <tbody>
            <tr v-for="user in users" :key="user.user_id">
              <th scope="row">{{ user.username }}<span v-if="user.user_id === session.user.user_id" class="admin-user-self">当前账户</span></th>
              <td data-label="角色">{{ user.role === 'admin' ? '管理员' : '用户' }}</td>
              <td data-label="状态"><span class="admin-user-status" :class="user.status === 'active' ? 'is-active' : 'is-disabled'">{{ user.status === 'active' ? '正常使用' : '已停用' }}</span></td>
              <td data-label="创建时间">{{ formatCreatedAt(user.created_at_utc_ms) }}</td>
              <td data-label="操作">
                <button v-if="user.status === 'active'" class="danger-button" type="button" :disabled="Boolean(busyUserId) || user.user_id === session.user.user_id || (user.role === 'admin' && summary.active_admins <= 1)" @click="setUserEnabled(user)">停用</button>
                <button v-else class="secondary-button" type="button" :disabled="Boolean(busyUserId)" @click="setUserEnabled(user)">重新启用</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <footer v-if="status === 'ready' && total > pageSize" class="admin-user-pagination" aria-label="用户列表分页">
        <span>第 {{ currentPage }} / {{ pageCount }} 页 · {{ total }} 个账户</span>
        <div><button class="secondary-button" type="button" :disabled="offset === 0 || status === 'loading'" @click="load(Math.max(0, offset - pageSize))">上一页</button><button class="secondary-button" type="button" :disabled="offset + pageSize >= total || status === 'loading'" @click="load(offset + pageSize)">下一页</button></div>
      </footer>
    </section>
  </section>
</template>

<style scoped>
.admin-users-page{display:grid;gap:16px;min-width:0}
.admin-user-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}
.admin-stat{display:grid;gap:8px;padding:16px;min-width:0}
.admin-stat>span,.admin-stat small{color:var(--muted);font-size:13px}
.admin-stat strong{font-size:30px;line-height:1.1;font-variant-numeric:tabular-nums}
.admin-user-panel{display:grid;gap:16px;padding:16px;min-width:0}
.admin-user-heading{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}
.admin-user-heading h2{margin:0}
.admin-user-heading p{margin:4px 0 0;font-size:13px}
.admin-user-filters{display:grid;grid-template-columns:minmax(180px,1fr) minmax(150px,.6fr) minmax(150px,.6fr) auto auto;align-items:end;gap:8px}
.admin-user-filters .field{margin:0;min-width:0;font-size:13px}
.admin-user-filters input,.admin-user-filters select{min-height:var(--control-height);width:100%}
.admin-user-filters button{min-height:var(--control-height)}
.admin-user-table-scroll{overflow-x:auto;min-width:0}
.admin-user-table{width:100%;border-collapse:collapse;text-align:left;font-size:14px}
.admin-user-table th,.admin-user-table td{padding:12px 8px;border-bottom:1px solid var(--line);vertical-align:middle}
.admin-user-table thead th{color:var(--muted);font-size:12px;font-weight:600}
.admin-user-self{display:inline-block;margin-left:8px;padding:2px 8px;border-radius:999px;background:var(--brand-soft);color:var(--brand);font-size:11px}
.admin-user-status{display:inline-flex;padding:4px 8px;border-radius:999px;font-size:12px;font-weight:600;white-space:nowrap}
.admin-user-status.is-active{background:var(--success-soft);color:var(--success)}
.admin-user-status.is-disabled{background:var(--danger-soft);color:var(--danger)}
.admin-user-table button{min-height:36px;padding:6px 12px}
.admin-user-empty{margin:0;padding:24px;border-radius:12px;background:var(--page);color:var(--muted);text-align:center}
.admin-user-pagination{display:flex;justify-content:space-between;align-items:center;gap:12px;color:var(--muted);font-size:13px}
.admin-user-pagination>div{display:flex;gap:8px}
.admin-user-pagination button{min-height:36px}
@media(max-width:850px){.admin-user-stats{grid-template-columns:repeat(2,minmax(0,1fr))}.admin-user-filters{grid-template-columns:repeat(2,minmax(0,1fr))}.admin-user-search{grid-column:1/-1}}
@media(max-width:640px){
  .admin-user-filters{grid-template-columns:minmax(0,1fr)}.admin-user-search{grid-column:auto}.admin-user-filters button{width:100%}
  .admin-user-table-scroll{overflow:visible}.admin-user-table,.admin-user-table tbody{display:block}.admin-user-table thead{display:none}
  .admin-user-table tr{display:grid;gap:0;margin-bottom:12px;padding:14px;border:1px solid var(--line);border-radius:14px;background:var(--page)}
  .admin-user-table th[scope=row]{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:0 0 12px;border-bottom:1px solid var(--line);overflow-wrap:anywhere}
  .admin-user-table td{display:grid;grid-template-columns:minmax(88px,.8fr) minmax(0,1.2fr);align-items:center;gap:8px;padding:10px 0;border-bottom:1px solid var(--line);text-align:right;overflow-wrap:anywhere}
  .admin-user-table td:last-child{border-bottom:0;padding-bottom:0}.admin-user-table td::before{content:attr(data-label);color:var(--muted);font-size:12px;font-weight:600;text-align:left}
  .admin-user-table td button{width:100%;min-height:44px}.admin-user-pagination{align-items:stretch;flex-direction:column}.admin-user-pagination>div{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}.admin-user-pagination button{min-height:44px}
}
</style>
