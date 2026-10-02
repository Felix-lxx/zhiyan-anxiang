<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AtlasLogin from './components/AtlasLogin.vue'
import './entry.css'
import { ApiError, createApiClient, setUnauthorizedHandler } from './api/client'
import type { Community, CurrentUser, HealthResponse, LoginResponse } from './domain/models'
import type { AccountProfile } from './domain/account'
import { applyAccountProfile } from './api/account'
import './styles/readability.css'

type HealthState = 'checking' | 'healthy' | 'degraded' | 'unreachable'
type AppView = 'login' | 'projects' | 'map' | 'scenes' | 'operations' | 'participant'

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? `${location.protocol}//${location.hostname}:8000/api/v1`
const route = useRoute()
const router = useRouter()
const username = ref('admin')
const password = ref('')
const isSubmitting = ref(false)
const loginError = ref('')
const healthState = ref<HealthState>('checking')
const healthDetail = ref('正在连接服务…')
const accessToken = ref(localStorage.getItem('zhiyan_access_token'))
const activeUsername = ref('')
const activeRole = ref('')
const selectedCommunity = ref<Community | null>(null)
const routeError = ref('')
const sessionReady = ref(false)
const communityLoading = ref(false)
let communityGeneration = 0
const activeView = computed<AppView>(() => {
  const names: Record<string, AppView> = { login: 'login', projects: 'projects', map: 'map', scenes: 'scenes', operations: 'operations', 'participant-local': 'participant', 'participant-invite': 'participant' }
  return names[String(route.name)] ?? (accessToken.value ? 'projects' : 'login')
})
const participantDrillId = computed(() => route.name === 'participant-invite' ? String(route.params.drillId ?? '') : '')
const participantInviteCode = computed(() => route.name === 'participant-invite' ? String(route.query.code ?? '') : '')
const api = createApiClient(apiBaseUrl, () => accessToken.value)
setUnauthorizedHandler(() => {
  const redirect = route.fullPath
  clearSession()
  loginError.value = '登录已失效，请重新登录。'
  if (!route.meta.public) void router.replace({ name: 'login', query: { redirect } })
})

const statusLabel = computed(() => {
  const labels: Record<HealthState, string> = {
    checking: '正在检查服务',
    healthy: '服务已就绪',
    degraded: '服务降级运行',
    unreachable: '服务暂不可达',
  }
  return labels[healthState.value]
})

async function checkHealth(): Promise<void> {
  healthState.value = 'checking'
  healthDetail.value = '正在连接服务…'

  try {
    const payload = await api.get<HealthResponse>('/health', { auth: false })
    healthState.value = payload.status
    healthDetail.value =
      payload.database.status === 'healthy'
        ? '应用与数据库连接正常'
        : '应用可用，数据库尚未连接；可先检查本地容器'
  } catch {
    healthState.value = 'unreachable'
    healthDetail.value = '未连接到后端，请先启动 FastAPI 服务'
  }
}

async function submitLogin(): Promise<void> {
  loginError.value = ''
  isSubmitting.value = true

  try {
    const payload = await api.post<LoginResponse>('/auth/login', { username: username.value.trim(), password: password.value }, { auth: false })

    accessToken.value = payload.access_token
    activeUsername.value = payload.username
    activeRole.value = payload.role
    localStorage.setItem('zhiyan_access_token', payload.access_token)
    await loadAccountProfile()
    const redirect = typeof route.query.redirect === 'string' && route.query.redirect.startsWith('/') ? route.query.redirect : '/projects'
    await router.replace(redirect)
  } catch (error) {
    loginError.value = error instanceof TypeError ? '暂时无法连接服务，请检查服务状态后重试。' : error instanceof Error ? error.message : '登录失败，请检查服务与账号信息。'
  } finally {
    isSubmitting.value = false
  }
}

async function joinByCode(code: string): Promise<void> {
  loginError.value = ''; isSubmitting.value = true
  try {
    if (!/^[a-f0-9]{6}$/i.test(code)) throw new Error('请输入导演提供的 6 位演练加入码。')
    const invite = await api.get<{ drill_id: string; code: string }>(`/participant/resolve?code=${encodeURIComponent(code)}`, { auth: false })
    await router.push({ name: 'participant-invite', params: { drillId: invite.drill_id }, query: { code: invite.code } })
  } catch (cause) { loginError.value = cause instanceof Error ? cause.message : '加入失败，请重试。' }
  finally { isSubmitting.value = false }
}

async function restoreSession(): Promise<void> {
  if (!accessToken.value) { sessionReady.value = true; return }

  try {
    const payload = await api.get<CurrentUser>('/auth/me')
    activeUsername.value = payload.username
    activeRole.value = payload.role
    await loadAccountProfile()
    if (route.name === 'login') {
      const redirect = typeof route.query.redirect === 'string' && route.query.redirect.startsWith('/') ? route.query.redirect : '/projects'
      await router.replace(redirect)
    }
  } catch (cause) {
    if (!(cause instanceof ApiError && cause.status === 401)) routeError.value = '暂时无法验证登录，请检查服务后重试。'
  } finally { sessionReady.value = true }
}

async function loadAccountProfile() {
  try { applyAccountProfile(await api.get<AccountProfile>('/account/profile')) }
  catch { applyAccountProfile(null) } // Account service failure must not hide the main workspace.
}
function clearSession(): void {
  applyAccountProfile(null)
  localStorage.removeItem('zhiyan_access_token')
  accessToken.value = null
  activeUsername.value = ''
  activeRole.value = ''
  password.value = ''
  selectedCommunity.value = null
}
function logout(): void { clearSession(); void router.replace('/login') }

function openMap(community: Community): void {
  selectedCommunity.value = community
  void router.push({ name: 'map', params: { communityId: community.id } })
}
function openOperations(community: Community): void { selectedCommunity.value = community; void router.push({ name: 'operations', params: { communityId: community.id }, query: { autostart: '1' } }) }
function openDrill(sceneId: string, drillId: string): void { if (selectedCommunity.value) void router.push({ name: 'operations', params: { communityId: selectedCommunity.value.id }, query: { scene: sceneId, drill: drillId } }) }
function openParticipant(): void { if (selectedCommunity.value) void router.push({ name: 'participant-local', params: { communityId: selectedCommunity.value.id } }) }
function returnToOperations(): void { if (selectedCommunity.value) void router.push({ name: 'operations', params: { communityId: selectedCommunity.value.id } }) }
function leaveParticipant(): void {
  if (participantDrillId.value) { void router.replace(accessToken.value ? '/projects' : '/login'); return }
  returnToOperations()
}

function returnToProjects(): void {
  selectedCommunity.value = null
  void router.push('/projects')
}
function openScenes(): void { if (selectedCommunity.value) void router.push({ name: 'scenes', params: { communityId: selectedCommunity.value.id } }) }
function returnToMap(): void { if (selectedCommunity.value) void router.push({ name: 'map', params: { communityId: selectedCommunity.value.id } }) }

async function syncRouteCommunity(): Promise<void> {
  const generation = ++communityGeneration
  const communityId = typeof route.params.communityId === 'string' ? route.params.communityId : ''
  if (!communityId || !accessToken.value) { communityLoading.value = false; if (!communityId) selectedCommunity.value = null; return }
  if (selectedCommunity.value?.id === communityId) return
  routeError.value = ''
  selectedCommunity.value = null; communityLoading.value = true
  try { const community = await api.get<Community>(`/communities/${encodeURIComponent(communityId)}`); if (generation === communityGeneration) selectedCommunity.value = community }
  catch (cause) {
    if (generation !== communityGeneration) return
    routeError.value = cause instanceof Error ? cause.message : '社区项目加载失败。'
    selectedCommunity.value = null
  } finally { if (generation === communityGeneration) communityLoading.value = false }
}
function routeBack(): void { if (activeView.value === 'scenes') returnToMap(); else if (activeView.value === 'participant') leaveParticipant(); else returnToProjects() }

watch(() => [route.fullPath, accessToken.value] as const, async () => {
  const isPublic = Boolean(route.meta.public)
  if (!isPublic && !accessToken.value) {
    await router.replace({ name: 'login', query: route.path === '/projects' ? {} : { redirect: route.fullPath } })
    return
  }
  await syncRouteCommunity()
}, { immediate: true })

onMounted(() => {
  void checkHealth()
  const invite = location.hash.match(/^#\/participant\/([^?]+)\?code=([^&]+)/)
  if (invite) void router.replace({ name: 'participant-invite', params: { drillId: decodeURIComponent(invite[1]) }, query: { code: decodeURIComponent(invite[2]) } })
  else void restoreSession()
})
</script>

<template>
  <a class="skip-link" href="#main-content">跳到主要内容</a>
  <main id="main-content" v-if="activeView !== 'login' && ((!sessionReady && !participantDrillId) || communityLoading || routeError)" class="route-state" aria-live="polite">
    <h1>{{ routeError ? '页面暂时无法打开' : '正在打开工作空间…' }}</h1>
    <p v-if="routeError" role="alert">{{ routeError }}</p>
    <div v-if="routeError"><button class="primary-button" @click="routeError = ''; restoreSession(); syncRouteCommunity()">重新加载</button><button class="secondary-button" @click="routeError = ''; returnToProjects()">返回项目</button></div>
  </main>
  <RouterView v-else-if="activeView !== 'login' && (participantDrillId || accessToken && (activeView === 'projects' || selectedCommunity))" v-slot="{ Component }">
    <component :is="Component" :key="String(route.name) + String(route.params.communityId ?? route.params.drillId ?? '')" :api-base-url="apiBaseUrl" :access-token="accessToken" :community="selectedCommunity" :username="activeUsername" :role="activeRole" :drill-id="participantDrillId || undefined" :invite-code="participantInviteCode || undefined" @logout="logout" @open-map="openMap" @open-operations="openOperations" @open-drill="openDrill" @open-scenes="openScenes" @participant="openParticipant" @back="routeBack" />
  </RouterView>

  <AtlasLogin v-else v-model:username="username" v-model:password="password" :busy="isSubmitting" :error="loginError" :status="statusLabel" :detail="healthDetail" :healthy="healthState === 'healthy'" :checking="healthState === 'checking'" :unavailable="healthState === 'unreachable'" @login="submitLogin" @join="joinByCode" @check="checkHealth" />
</template>

<style scoped>
.route-state { min-height:100dvh; display:flex; flex-direction:column; justify-content:center; align-items:center; gap:1rem; padding:2rem; background:var(--surface-page,#f3f1e9); color:var(--text-primary,#173f3e); text-align:center }
.route-state h1 { font-size:1.6rem; margin:0 }
.route-state>div { display:flex; flex-wrap:wrap; gap:1rem }
</style>
