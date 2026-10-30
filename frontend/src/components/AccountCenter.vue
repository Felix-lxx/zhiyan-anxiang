<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router'
import { ApiError, createApiClient } from '../api/client'
import { applyAccountProfile } from '../api/account'
import type { AccountActivity, AccountProfile, AuthSessionInfo } from '../domain/account'
import type { Community } from '../domain/models'
import AppIcon from './AppIcon.vue'

const props = defineProps<{ apiBaseUrl: string; accessToken: string }>()
const emit = defineEmits<{ logout: [] }>()
const router = useRouter(), api = createApiClient(props.apiBaseUrl, () => props.accessToken)
const route = useRoute()
type AccountTab = 'profile' | 'preferences' | 'security'
const accountTabs: { id: AccountTab; label: string }[] = [{ id: 'profile', label: '个人资料' }, { id: 'preferences', label: '阅读与操作偏好' }, { id: 'security', label: '登录与安全' }]
const accountTab = computed<AccountTab>(() => accountTabs.some(tab => tab.id === route.query.accountTab) ? route.query.accountTab as AccountTab : 'profile')
function selectTab(tab: AccountTab) { void router.replace({ query: { ...route.query, accountTab: tab } }) }
const profile = ref<AccountProfile | null>(null), draft = ref<AccountProfile | null>(null)
const communities = ref<Community[]>([]), activity = ref<AccountActivity | null>(null)
const loading = ref(true), saving = ref(false), error = ref(''), notice = ref(''), activityError = ref(''), conflict = ref(false)
const sessions = ref<AuthSessionInfo[]>([]), sessionsLoading = ref(false), sessionsError = ref(''), revokingSessionId = ref('')
const dirty = computed(() => Boolean(profile.value && draft.value && JSON.stringify(profile.value) !== JSON.stringify(draft.value)))
const statusNames: Record<string, string> = { ready: '待开始', running: '进行中', paused: '已暂停', ended: '已结束', draft: '待准备' }
function date(value: string | null) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '尚未保存个人设置' }
async function loadActivity() {
  activityError.value = ''
  try { activity.value = await api.get<AccountActivity>('/account/activity') }
  catch (cause) { activityError.value = cause instanceof Error ? cause.message : '记录读取失败，请重试。' }
}
async function loadSessions() {
  sessionsLoading.value = true; sessionsError.value = ''
  try { sessions.value = await api.get<AuthSessionInfo[]>('/auth/sessions') }
  catch (cause) { sessionsError.value = cause instanceof Error ? cause.message : '登录会话读取失败，请重试。' }
  finally { sessionsLoading.value = false }
}
async function revokeSession(sessionId: string) {
  if (revokingSessionId.value || !window.confirm('结束这个登录会话后，对应设备需要重新登录。是否继续？')) return
  revokingSessionId.value = sessionId; sessionsError.value = ''
  try {
    await api.delete(`/auth/sessions/${sessionId}`)
    await loadSessions()
    notice.value = '指定登录会话已结束。'
  } catch (cause) { sessionsError.value = cause instanceof Error ? cause.message : '会话结束失败，请重试。' }
  finally { revokingSessionId.value = '' }
}
async function load() {
  if (dirty.value && !window.confirm('重新载入会放弃未保存的修改，是否继续？')) return
  loading.value = true; error.value = ''; conflict.value = false; notice.value = ''
  try {
    const [data, items] = await Promise.all([api.get<AccountProfile>('/account/profile'), api.get<Community[]>('/communities')])
    profile.value = data; draft.value = { ...data }; communities.value = items; applyAccountProfile(data)
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '资料读取失败，请重试。' }
  finally { loading.value = false }
}
async function save() {
  if (!draft.value || saving.value) return
  saving.value = true; error.value = ''; notice.value = ''; conflict.value = false
  const { display_name, organization, default_community_id, text_size, reduced_motion, revision } = draft.value
  try {
    const result = await api.patch<AccountProfile>('/account/profile', { display_name, organization, default_community_id, text_size, reduced_motion, revision })
    profile.value = result; draft.value = { ...result }; applyAccountProfile(result)
    notice.value = '资料与阅读设置已保存，刷新或再次登录后仍然生效。'
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '保存失败，输入已保留，请重试。'; conflict.value = cause instanceof ApiError && cause.status === 409 }
  finally { saving.value = false }
}
function allowLeave() { return !dirty.value || window.confirm('个人资料尚未保存，确定离开？') }
function logout() { if (allowLeave()) { draft.value = profile.value ? { ...profile.value } : null; emit('logout') } }
function beforeUnload(event: BeforeUnloadEvent) { if (dirty.value) event.preventDefault() }
function openRun(run: AccountActivity['recent'][number]) {
  void router.push({ name: 'operations', params: { communityId: run.community_id }, query: { scene: run.scene_id, drill: run.id, ...(run.status === 'ended' ? { mode: 'replay' } : {}) } })
}
onBeforeRouteLeave(allowLeave)
onBeforeRouteUpdate((to, from) => to.query.section === from.query.section || allowLeave())
onMounted(() => { window.addEventListener('beforeunload', beforeUnload); void load(); void loadActivity(); void loadSessions() })
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
</script>

<template>
  <section class="account-center" aria-labelledby="account-title" :aria-busy="loading">
    <header class="account-heading"><div><h1 id="account-title">个人中心</h1><p>管理你的工作资料、默认社区与阅读习惯。</p></div><button type="button" class="secondary-button" :disabled="loading || saving" @click="load"><AppIcon name="refresh" :size="18" />重新载入</button></header>
    <nav class="account-tabs" aria-label="个人中心分区"><button v-for="tab in accountTabs" :key="tab.id" type="button" :aria-current="accountTab === tab.id ? 'page' : undefined" @click="selectTab(tab.id)">{{tab.label}}</button></nav>
    <p v-if="loading" role="status">正在读取个人资料…</p>
    <div v-if="error" class="account-message" role="alert"><p>{{ error }}</p><button v-if="conflict || !profile" type="button" @click="load">重新载入最新资料</button></div>
    <p v-if="notice" class="account-notice" role="status">{{ notice }}</p>
    <div v-if="draft && profile" class="account-layout" :data-tab="accountTab">
      <div class="account-primary">
        <form v-show="accountTab !== 'security'" class="account-form" @submit.prevent="save">
        <section v-show="accountTab === 'profile'" class="account-section" aria-labelledby="identity-title"><header><AppIcon name="person" /><h2 id="identity-title">工作资料</h2></header>
          <dl class="account-identity"><div><dt>登录账号</dt><dd>{{ profile.username }}</dd></div><div><dt>当前身份</dt><dd>{{ profile.role }}</dd></div></dl>
          <div class="account-fields"><label for="profile-name">显示名称<input id="profile-name" v-model="draft.display_name" :disabled="saving" required maxlength="64" autocomplete="nickname" placeholder="请输入工作中使用的名称" /></label><label for="profile-organization">所属单位 <span>选填</span><input id="profile-organization" v-model="draft.organization" :disabled="saving" maxlength="100" autocomplete="organization" placeholder="例如：安巷社区物业服务中心" /></label></div>
        </section>
        <section v-show="accountTab === 'preferences'" class="account-section" aria-labelledby="preferences-title"><header><AppIcon name="settings" /><h2 id="preferences-title">工作与阅读设置</h2></header>
          <label class="account-preference-community" for="profile-community">默认打开的社区<select id="profile-community" v-model="draft.default_community_id" :disabled="saving"><option :value="null">按最近更新选择</option><option v-for="item in communities" :key="item.id" :value="item.id">{{ item.name }}</option></select><small>下次进入演练首页时生效，不改变正在运行的场次。</small></label>
          <fieldset class="account-preference-reading" :disabled="saving"><legend>文字大小</legend><label><input v-model="draft.text_size" type="radio" value="comfortable" name="reading-size" />舒适 · 正文 16 像素</label><label><input v-model="draft.text_size" type="radio" value="large" name="reading-size" />大字 · 正文 18 像素</label></fieldset>
          <label class="account-toggle"><input v-model="draft.reduced_motion" :disabled="saving" type="checkbox" /><span>减少界面动画<small>减少菜单与面板的过渡动画，不暂停三维仿真。</small></span></label>
        </section>
        <footer class="account-save"><span>{{ dirty ? '有未保存的修改' : `上次保存：${date(profile.updated_at)}` }}</span><button type="button" class="secondary-button" :disabled="!dirty || saving" @click="draft = { ...profile }; error = ''; notice = ''; conflict = false">撤销修改</button><button class="primary-button" type="submit" :disabled="!dirty || saving || conflict">{{ saving ? '正在保存…' : '保存设置' }}</button></footer>
        </form>
      <section v-show="accountTab === 'security'" class="account-section account-security" aria-labelledby="security-title">
        <header>
          <AppIcon name="lock" />
          <div><h2 id="security-title">登录与权限</h2><p>查看当前账号的登录范围与活动会话。</p></div>
          <button type="button" aria-label="刷新登录会话" :disabled="sessionsLoading" @click="loadSessions"><AppIcon name="refresh" :size="18" /></button>
        </header>
        <div class="account-security-grid">
          <div class="account-security-overview">
            <div class="account-role-summary">
              <div><span>当前身份</span><strong>{{ profile.role }}</strong></div>
              <div><span>认证方式</span><strong>{{ profile.authentication_mode === 'account_session' ? '正式账号会话' : '开发兼容凭证' }}</strong></div>
            </div>
            <div class="account-security-notes">
              <p class="account-security-note">{{ profile.authentication_mode === 'account_session' ? '访问凭证到期后会自动安全续期；结束其他会话可立即撤销对应设备的访问权限。' : '当前凭证仅用于本地开发，正式部署后需要重新登录。' }}</p>
              <p class="account-security-note">手机参演人员通过演练加入码进入，不共享管理端权限。</p>
            </div>
          </div>
          <div class="account-security-sessions" :aria-busy="sessionsLoading">
            <div class="account-session-heading"><h3>登录会话</h3><span>{{ sessions.filter(item => item.status === 'active').length }} 个活动会话</span></div>
            <p v-if="sessionsError" class="session-error" role="alert">{{ sessionsError }} <button type="button" @click="loadSessions">重试</button></p>
            <p v-else-if="sessionsLoading" role="status">正在读取登录会话…</p>
            <ul v-else class="account-session-list">
              <li v-for="item in sessions" :key="item.id" :data-current="item.current">
                <div>
                  <strong>{{ item.current ? '当前浏览器' : '其他登录会话' }}</strong>
                  <span>最近活动：{{ date(item.last_used_at) }}</span>
                </div>
                <span class="session-status" :class="`is-${item.status}`">{{ item.current ? '当前' : item.status === 'active' ? '活动' : item.status === 'expired' ? '已过期' : '已结束' }}</span>
                <button v-if="!item.current && item.status === 'active'" type="button" :disabled="Boolean(revokingSessionId)" @click="revokeSession(item.id)">{{ revokingSessionId === item.id ? '正在结束…' : '结束会话' }}</button>
              </li>
              <li v-if="!sessions.length" class="session-empty">暂未读取到正式登录会话。</li>
            </ul>
            <footer class="account-session-actions"><button type="button" class="secondary-button account-logout" :disabled="saving" @click="logout"><AppIcon name="logout" :size="18" />退出并结束当前会话</button></footer>
          </div>
        </div>
        </section>
      </div>
      <div v-show="accountTab === 'profile'" class="account-side">
        <section class="account-section account-activity" aria-labelledby="activity-title"><header><AppIcon name="history" /><h2 id="activity-title">我的演练</h2><button type="button" aria-label="刷新个人演练记录" @click="loadActivity"><AppIcon name="refresh" :size="18" /></button></header>
          <p v-if="activityError" role="alert">{{ activityError }}<button type="button" @click="loadActivity">重试</button></p>
          <template v-if="activity"><p class="account-summary">{{ activity.community_count }} 个社区 · {{ activity.drill_count }} 场演练<br />已结束 {{ activity.completed_count }} 场，未完成 {{ activity.unfinished_count }} 场</p>
            <ol><li v-for="run in activity.recent.slice(0, 4)" :key="run.id"><div><strong>{{ run.name }}</strong><span>{{ run.community_name }} · {{ statusNames[run.status] ?? run.status }}</span><time>{{ date(run.created_at) }}</time></div><button type="button" @click="openRun(run)">{{ run.status === 'ended' ? '查看复盘' : '进入演练' }}<AppIcon name="arrowRight" :size="16" /></button></li></ol>
            <p v-if="!activity.recent.length">还没有演练记录。先在「场景准备」配置社区，再开始第一场训练。</p>
          </template><p v-else-if="!activityError" role="status">正在读取演练记录…</p>
          <button type="button" class="account-history-link" @click="router.push({ name: 'projects', query: { section: 'history' } })">筛选全部复盘记录<AppIcon name="arrowRight" :size="18" /></button>
        </section>
      </div>
    </div>
  </section>
</template>

<style scoped>
.account-center{padding:var(--space-8) var(--atlas-gutter);font-size:var(--ui-body-size);line-height:1.65;min-width:0}
.account-tabs{display:flex;gap:8px;overflow-x:auto;padding:16px 0;border-bottom:1px solid var(--border-default)}.account-tabs button{flex:none;padding:10px 16px;border:0;border-radius:var(--radius-sm);background:transparent;color:var(--text-secondary)}.account-tabs button[aria-current=page]{background:var(--color-brand-100);color:var(--action-primary);font-weight:700}.account-layout[data-tab=preferences]{grid-template-columns:minmax(0,1fr);grid-template-areas:'form'}.account-layout[data-tab=security]{grid-template-columns:minmax(0,1fr);grid-template-areas:'security'}
.account-heading{display:flex;align-items:center;justify-content:space-between;gap:var(--space-6);padding-bottom:var(--space-6);border-bottom:1px solid var(--border-default)}
.account-heading h1{font:700 32px/1.4 var(--atlas-display);margin:0}.account-heading p{margin:8px 0 0;color:var(--text-secondary)}
.account-layout{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);grid-template-areas:"form activity" "security security";column-gap:var(--space-10);row-gap:0;align-items:start}.account-primary{display:contents}.account-form{grid-area:form}.account-side{grid-area:activity}.account-security{grid-area:security}.account-form,.account-side,.account-security{min-width:0}.account-section{padding:var(--space-6) 0;border-bottom:1px solid var(--border-default)}
.account-section>header{display:flex;align-items:center;gap:12px;margin-bottom:20px}.account-section h2{font-size:21px;margin:0}.account-section>header>button{margin-left:auto}.account-section>header>div{min-width:0}.account-section>header>div>p{margin:3px 0 0;color:var(--text-secondary)}
.account-identity{display:flex;flex-wrap:wrap;gap:16px 32px;margin:0 0 24px}.account-identity>div{display:flex;gap:12px}.account-identity dt{color:var(--text-secondary)}.account-identity dd{margin:0;font-weight:600;overflow-wrap:anywhere}
.account-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.account-form label{display:block;font-weight:600}.account-form label>span:not(.account-toggle span){font-weight:400;color:var(--text-secondary)}
.account-form :is(input:not([type=radio]):not([type=checkbox]),select){width:100%;min-width:0;min-height:48px;font:inherit;margin-top:8px;padding:10px 12px;background:var(--surface-raised);color:var(--text-primary);border:1px solid var(--border-default);border-radius:var(--radius-sm)}
.account-form small{display:block;font-weight:400;font-size:var(--ui-meta-size);color:var(--text-secondary);margin-top:8px}
.account-form fieldset{border:0;padding:0;margin:24px 0;min-width:0}.account-form legend{font-weight:600;margin-bottom:8px}.account-form fieldset label{display:inline-flex;align-items:center;gap:10px;min-height:44px;margin-right:20px;font-weight:400}
.account-form input:is([type=radio],[type=checkbox]){width:20px;height:20px;min-height:20px;flex-shrink:0;padding:0;margin:0;accent-color:var(--action-primary)}
.account-form .account-toggle{display:flex;align-items:flex-start;gap:12px}.account-toggle>input{margin-top:4px!important}
.account-save{display:grid;grid-template-columns:max-content max-content;align-items:center;justify-content:start;gap:12px;padding:24px 0}.account-save>span{grid-column:1/-1;color:var(--text-secondary);font-size:var(--ui-meta-size)}.account-save :is(.primary-button,.secondary-button){width:auto;height:44px;min-height:44px;margin:0;padding:0 16px;line-height:1;white-space:nowrap}
.account-center button{min-height:44px;display:inline-flex;align-items:center;justify-content:center;gap:8px;font:inherit;cursor:pointer}.account-center button:disabled{cursor:not-allowed;opacity:.55}
.account-section>header>button,.account-activity li button,.account-history-link{background:transparent;color:var(--action-primary);border:0;padding:8px 0}.account-section>header>button{min-width:44px}
.account-summary{margin:0 0 12px;color:var(--text-secondary)}.account-activity ol{list-style:none;margin:0;padding:0}.account-activity li{display:flex;align-items:center;gap:16px;padding:16px 0;border-top:1px solid var(--border-default)}
.account-activity li>div{flex:1;min-width:0}.account-activity li strong,.account-activity li span,.account-activity li time{display:block;overflow-wrap:anywhere}.account-activity li span,.account-activity time{color:var(--text-secondary);font-size:var(--ui-meta-size)}.account-activity li button{flex-shrink:0}
.account-history-link{margin-top:16px;text-decoration:underline;text-underline-offset:4px}
.account-security{container-type:inline-size}
.account-security-grid{display:grid;grid-template-columns:minmax(0,1fr);gap:var(--space-6)}
.account-security-overview{display:grid;grid-template-columns:minmax(0,.9fr) minmax(0,1.1fr);align-items:start;gap:var(--space-8)}
.account-security-notes,.account-security-sessions{min-width:0}
.account-security-note{color:var(--text-secondary);margin:0;overflow-wrap:anywhere}
.account-security-note+.account-security-note{margin-top:var(--space-2)}
.account-role-summary{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1px;background:var(--border-default);border:1px solid var(--border-default);border-radius:var(--radius-sm);overflow:hidden}
.account-role-summary>div{display:grid;gap:var(--space-1);padding:var(--space-3) var(--space-4);background:var(--surface-raised)}
.account-role-summary span{color:var(--text-secondary);font-size:var(--ui-meta-size)}
.account-role-summary strong{overflow-wrap:anywhere}
.account-session-heading{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:var(--space-2) var(--space-4);margin:0}
.account-session-heading h3{font-size:18px;margin:0}
.account-session-heading span{color:var(--text-secondary);font-size:var(--ui-meta-size)}
.account-session-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));column-gap:var(--space-8);list-style:none;margin:var(--space-3) 0 0;padding:0;border-top:1px solid var(--border-default)}
.account-session-list li{display:grid;grid-template-columns:minmax(0,1fr) auto auto;align-items:center;gap:var(--space-3);padding:var(--space-4) 0;border-bottom:1px solid var(--border-default)}
.account-session-list li>div{min-width:0}
.account-session-list li strong,.account-session-list li>div span{display:block;overflow-wrap:anywhere}
.account-session-list li>div span{color:var(--text-secondary);font-size:var(--ui-meta-size);margin-top:var(--space-1);font-variant-numeric:tabular-nums}
.session-status{min-width:54px;text-align:center;padding:4px 8px;border-radius:999px;background:var(--surface-panel);color:var(--text-secondary);font-size:var(--ui-meta-size)}
.session-status.is-active{background:var(--color-success-soft);color:var(--status-success)}
.account-session-list li>button,.session-error button{min-height:var(--control-height);padding:var(--space-2);background:transparent;color:var(--action-primary);border:0;text-decoration:underline;text-underline-offset:3px;white-space:nowrap}
.account-session-list .session-empty{display:block;grid-column:1/-1;color:var(--text-secondary)}
.session-error{color:var(--status-danger);margin:var(--space-3) 0}
.account-session-actions{display:flex;justify-content:flex-end;padding-top:var(--space-5)}
.account-logout{margin:0}
@container(max-width:800px){.account-security-overview{grid-template-columns:1fr;gap:var(--space-4)}.account-session-list{grid-template-columns:1fr}}
@container(max-width:420px){.account-session-list li{grid-template-columns:minmax(0,1fr) auto}.account-session-list li>button{grid-column:1/-1;justify-self:start;padding-left:0}.account-session-actions{justify-content:stretch}.account-logout{width:100%}}
.account-message,.account-notice{padding:16px 20px;margin:20px 0;background:var(--color-danger-soft);color:var(--status-danger);border-radius:var(--radius-sm)}.account-message p{margin:0}.account-notice{background:var(--color-success-soft);color:var(--status-success)}
@media(max-width:1150px){.account-layout{column-gap:24px;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr)}.account-security-grid{gap:24px}.account-fields{grid-template-columns:1fr}}
@media(max-width:820px){.account-layout{grid-template-columns:1fr;grid-template-areas:"form" "security" "activity"}.account-security-grid{grid-template-columns:1fr}.account-center{padding:24px 16px}.account-heading{align-items:flex-start;flex-wrap:wrap}.account-activity li{flex-wrap:wrap}.account-fields{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:540px){.account-fields,.account-role-summary{grid-template-columns:1fr}.account-identity{display:grid;gap:12px}.account-save{grid-template-columns:repeat(2,minmax(0,1fr))}.account-save button{width:100%}.account-heading h1{font-size:28px}.account-session-list li{grid-template-columns:minmax(0,1fr) auto}.account-session-list li>button{grid-column:1/-1;justify-self:start;padding-left:0}}
.account-layout[data-tab=preferences] .account-section{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);grid-template-areas:"heading heading" "community reading" "motion reading";gap:24px 40px;align-items:start}
.account-layout[data-tab=preferences] .account-section>header{grid-area:heading;margin:0}.account-preference-community{grid-area:community}.account-preference-reading{grid-area:reading;margin:0!important}.account-layout[data-tab=preferences] .account-toggle{grid-area:motion}.account-preference-reading label{display:flex!important;margin:0!important}.account-layout[data-tab=preferences] .account-save{border-top:0}
@media(max-width:820px){.account-layout[data-tab=preferences] .account-section{grid-template-columns:1fr;grid-template-areas:"heading" "community" "reading" "motion";gap:24px}}
</style>
