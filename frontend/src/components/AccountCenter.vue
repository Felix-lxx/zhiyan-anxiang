<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRouter } from 'vue-router'
import { ApiError, createApiClient } from '../api/client'
import { applyAccountProfile } from '../api/account'
import type { AccountActivity, AccountProfile } from '../domain/account'
import type { Community } from '../domain/models'
import AppIcon from './AppIcon.vue'

const props = defineProps<{ apiBaseUrl: string; accessToken: string }>()
const emit = defineEmits<{ logout: [] }>()
const router = useRouter(), api = createApiClient(props.apiBaseUrl, () => props.accessToken)
const profile = ref<AccountProfile | null>(null), draft = ref<AccountProfile | null>(null)
const communities = ref<Community[]>([]), activity = ref<AccountActivity | null>(null)
const loading = ref(true), saving = ref(false), error = ref(''), notice = ref(''), activityError = ref(''), conflict = ref(false)
const dirty = computed(() => Boolean(profile.value && draft.value && JSON.stringify(profile.value) !== JSON.stringify(draft.value)))
const statusNames: Record<string, string> = { ready: '待开始', running: '进行中', paused: '已暂停', ended: '已结束', draft: '待准备' }
function date(value: string | null) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '尚未保存个人设置' }
async function loadActivity() {
  activityError.value = ''
  try { activity.value = await api.get<AccountActivity>('/account/activity') }
  catch (cause) { activityError.value = cause instanceof Error ? cause.message : '记录读取失败，请重试。' }
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
onMounted(() => { window.addEventListener('beforeunload', beforeUnload); void load(); void loadActivity() })
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
</script>

<template>
  <section class="account-center" aria-labelledby="account-title" :aria-busy="loading">
    <header class="account-heading"><div><h1 id="account-title">个人中心</h1><p>管理你的工作资料、默认社区与阅读习惯。</p></div><button type="button" class="secondary-button" :disabled="loading || saving" @click="load"><AppIcon name="refresh" :size="18" />重新载入</button></header>
    <p v-if="loading" role="status">正在读取个人资料…</p>
    <div v-if="error" class="account-message" role="alert"><p>{{ error }}</p><button v-if="conflict || !profile" type="button" @click="load">重新载入最新资料</button></div>
    <p v-if="notice" class="account-notice" role="status">{{ notice }}</p>
    <div v-if="draft && profile" class="account-layout">
      <form class="account-form" @submit.prevent="save">
        <section class="account-section" aria-labelledby="identity-title"><header><AppIcon name="person" /><h2 id="identity-title">工作资料</h2></header>
          <dl class="account-identity"><div><dt>登录账号</dt><dd>{{ profile.username }}</dd></div><div><dt>当前身份</dt><dd>{{ profile.role }}</dd></div></dl>
          <div class="account-fields"><label for="profile-name">显示名称<input id="profile-name" v-model="draft.display_name" :disabled="saving" required maxlength="64" autocomplete="nickname" placeholder="请输入工作中使用的名称" /></label><label for="profile-organization">所属单位 <span>选填</span><input id="profile-organization" v-model="draft.organization" :disabled="saving" maxlength="100" autocomplete="organization" placeholder="例如：安巷社区物业服务中心" /></label></div>
        </section>
        <section class="account-section" aria-labelledby="preferences-title"><header><AppIcon name="settings" /><h2 id="preferences-title">工作与阅读设置</h2></header>
          <label for="profile-community">默认打开的社区<select id="profile-community" v-model="draft.default_community_id" :disabled="saving"><option :value="null">按最近更新选择</option><option v-for="item in communities" :key="item.id" :value="item.id">{{ item.name }}</option></select><small>下次进入演练首页时生效，不改变正在运行的场次。</small></label>
          <fieldset :disabled="saving"><legend>文字大小</legend><label><input v-model="draft.text_size" type="radio" value="comfortable" name="reading-size" />舒适 · 正文 16 像素</label><label><input v-model="draft.text_size" type="radio" value="large" name="reading-size" />大字 · 正文 18 像素</label></fieldset>
          <label class="account-toggle"><input v-model="draft.reduced_motion" :disabled="saving" type="checkbox" /><span>减少界面动画<small>减少菜单与面板的过渡动画，不暂停三维仿真。</small></span></label>
        </section>
        <footer class="account-save"><span>{{ dirty ? '有未保存的修改' : `上次保存：${date(profile.updated_at)}` }}</span><button type="button" class="secondary-button" :disabled="!dirty || saving" @click="draft = { ...profile }; error = ''; notice = ''; conflict = false">撤销修改</button><button class="primary-button" type="submit" :disabled="!dirty || saving || conflict">{{ saving ? '正在保存…' : '保存设置' }}</button></footer>
      </form>
      <div class="account-side">
        <section class="account-section account-activity" aria-labelledby="activity-title"><header><AppIcon name="history" /><h2 id="activity-title">我的演练</h2><button type="button" aria-label="刷新个人演练记录" @click="loadActivity"><AppIcon name="refresh" :size="18" /></button></header>
          <p v-if="activityError" role="alert">{{ activityError }}<button type="button" @click="loadActivity">重试</button></p>
          <template v-if="activity"><p class="account-summary">{{ activity.community_count }} 个社区 · {{ activity.drill_count }} 场演练<br />已结束 {{ activity.completed_count }} 场，未完成 {{ activity.unfinished_count }} 场</p>
            <ol><li v-for="run in activity.recent" :key="run.id"><div><strong>{{ run.name }}</strong><span>{{ run.community_name }} · {{ statusNames[run.status] ?? run.status }}</span><time>{{ date(run.created_at) }}</time></div><button type="button" @click="openRun(run)">{{ run.status === 'ended' ? '查看复盘' : '进入演练' }}<AppIcon name="arrowRight" :size="16" /></button></li></ol>
            <p v-if="!activity.recent.length">还没有演练记录。先在「场景准备」配置社区，再开始第一场训练。</p>
          </template><p v-else-if="!activityError" role="status">正在读取演练记录…</p>
          <button type="button" class="account-history-link" @click="router.push({ name: 'projects', query: { section: 'history' } })">筛选全部复盘记录<AppIcon name="arrowRight" :size="18" /></button>
        </section>
        <section class="account-section account-security" aria-labelledby="security-title"><header><AppIcon name="lock" /><h2 id="security-title">登录与权限</h2></header><p>当前使用开发环境账号。显示名称与阅读设置不会改变登录名、密码或社区访问权限。</p><p>当前版本暂不支持在线修改密码或角色；登录凭据由系统配置管理。</p><button type="button" class="secondary-button" :disabled="saving" @click="logout"><AppIcon name="logout" :size="18" />退出当前登录</button></section>
      </div>
    </div>
  </section>
</template>

<style scoped>
.account-center{padding:var(--space-8) var(--atlas-gutter);font-size:var(--ui-body-size);line-height:1.65;min-width:0}
.account-heading{display:flex;align-items:center;justify-content:space-between;gap:var(--space-6);padding-bottom:var(--space-6);border-bottom:1px solid var(--border-default)}
.account-heading h1{font:700 32px/1.4 var(--atlas-display);margin:0}.account-heading p{margin:8px 0 0;color:var(--text-secondary)}
.account-layout{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:var(--space-10);align-items:start}
.account-layout>*{min-width:0}.account-section{padding:var(--space-6) 0;border-bottom:1px solid var(--border-default)}
.account-section>header{display:flex;align-items:center;gap:12px;margin-bottom:20px}.account-section h2{font-size:21px;margin:0}.account-section>header>button{margin-left:auto}
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
.account-history-link{margin-top:16px;text-decoration:underline;text-underline-offset:4px}.account-security p{color:var(--text-secondary);margin:12px 0}.account-security button{margin-top:12px}
.account-message,.account-notice{padding:16px 20px;margin:20px 0;background:var(--color-danger-soft);color:var(--status-danger);border-radius:var(--radius-sm)}.account-message p{margin:0}.account-notice{background:var(--color-success-soft);color:var(--status-success)}
@media(max-width:1150px){.account-layout{gap:24px;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr)}.account-fields{grid-template-columns:1fr}}
@media(max-width:820px){.account-layout{grid-template-columns:1fr}.account-center{padding:24px 16px}.account-heading{align-items:flex-start;flex-wrap:wrap}.account-activity li{flex-wrap:wrap}.account-fields{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:540px){.account-fields{grid-template-columns:1fr}.account-identity{display:grid;gap:12px}.account-save{grid-template-columns:repeat(2,minmax(0,1fr))}.account-save button{width:100%}.account-heading h1{font-size:28px}}
</style>
