<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from './components/AppIcon.vue'
import './entry.css'
import { ApiError, createApiClient, setUnauthorizedHandler } from './api/client'
import type { Community, CurrentUser, HealthResponse, LoginResponse } from './domain/models'

type HealthState = 'checking' | 'healthy' | 'degraded' | 'unreachable'
type AppView = 'login' | 'projects' | 'map' | 'scenes' | 'operations' | 'participant'

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? `${location.protocol}//${location.hostname}:8000/api/v1`
const route = useRoute()
const router = useRouter()
const username = ref('admin')
const password = ref('')
const showPassword = ref(false)
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
    const redirect = typeof route.query.redirect === 'string' && route.query.redirect.startsWith('/') ? route.query.redirect : '/projects'
    await router.replace(redirect)
  } catch (error) {
    loginError.value = error instanceof TypeError ? '暂时无法连接服务，请检查服务状态后重试。' : error instanceof Error ? error.message : '登录失败，请检查服务与账号信息。'
  } finally {
    isSubmitting.value = false
  }
}

async function restoreSession(): Promise<void> {
  if (!accessToken.value) { sessionReady.value = true; return }

  try {
    const payload = await api.get<CurrentUser>('/auth/me')
    activeUsername.value = payload.username
    activeRole.value = payload.role
    if (route.name === 'login') {
      const redirect = typeof route.query.redirect === 'string' && route.query.redirect.startsWith('/') ? route.query.redirect : '/projects'
      await router.replace(redirect)
    }
  } catch (cause) {
    if (!(cause instanceof ApiError && cause.status === 401)) routeError.value = '暂时无法验证登录，请检查服务后重试。'
  } finally { sessionReady.value = true }
}

function clearSession(): void {
  localStorage.removeItem('zhiyan_access_token')
  accessToken.value = null
  activeUsername.value = ''
  activeRole.value = ''
  password.value = ''
  showPassword.value = false
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

  <main id="main-content" v-else class="entry-login">
    <section class="entry-auth" aria-labelledby="login-title">
      <div class="entry-brand"><span class="entry-brand__symbol"><AppIcon name="compass" :size="26" /></span><div>智演安巷<span>社区消防演练平台</span></div></div>
      <div class="entry-auth__body">
        <div class="entry-auth__heading">
          <h1 id="login-title">登录工作空间</h1>
          <p>继续你的社区项目与消防演练。</p>
        </div>
        <form class="login-form entry-form" @submit.prevent="submitLogin">
          <div class="entry-field">
            <label for="username">账号</label>
            <div class="entry-input"><AppIcon name="person" /><input id="username" v-model="username" autocomplete="username" maxlength="64" required placeholder="输入工作台账号" :disabled="isSubmitting" /></div>
          </div>
          <div class="entry-field">
            <label for="password">密码</label>
            <div class="entry-input"><AppIcon name="lock" /><input id="password" v-model="password" autocomplete="current-password" :type="showPassword ? 'text' : 'password'" minlength="1" maxlength="128" required placeholder="输入登录密码" :disabled="isSubmitting" /><button type="button" class="entry-reveal" :aria-label="showPassword ? '隐藏密码' : '显示密码'" :aria-pressed="showPassword" @click="showPassword = !showPassword"><AppIcon :name="showPassword ? 'eyeOff' : 'eye'" /></button></div>
          </div>
          <p v-if="loginError" class="message message--error" role="alert">{{ loginError }}</p>
          <button class="entry-button entry-button--primary entry-submit" type="submit" :disabled="isSubmitting || healthState === 'unreachable'">
            <span>{{ isSubmitting ? '正在验证账号…' : '登录演练工作台' }}</span><AppIcon name="arrowRight" />
          </button>
          <p class="entry-auth-note"><AppIcon name="lock" :size="16" /><span>使用本地配置的账号。需要访问权限？请联系项目管理员。</span></p>
        </form>
        <div class="entry-health" :data-state="healthState" aria-live="polite">
          <span class="status-dot" aria-hidden="true"></span>
          <div><strong>{{ statusLabel }}</strong><p>{{ healthDetail }}</p></div>
          <button class="entry-link" type="button" :disabled="healthState === 'checking'" @click="checkHealth">重新检查</button>
        </div>
      </div>
      <footer class="entry-auth__footer"><AppIcon name="inspect" :size="16" /><span>训练模拟，不替代现场消防专业判断。</span></footer>
    </section>
    <section class="entry-story" aria-labelledby="product-title">
      <figure class="entry-scene">
        <img src="/assets/plates/community-photo.png" alt="老旧住宅外立面的窗户、防盗网与空调外机，上海社区建筑参考影像" width="668" height="1130" fetchpriority="high" />
        <figcaption><span>上海 · 社区建筑参考影像，非项目实测社区</span><a href="https://unsplash.com/photos/fkNWzC4ybJ8" target="_blank" rel="noopener noreferrer">摄影 Zeg Young / Unsplash</a></figcaption>
      </figure>
      <div class="entry-story__copy">
        <h2 id="product-title">把演练带回社区。</h2>
        <p>从熟悉的楼栋与街巷出发，在三维现场练习撤离、调度与协作，让每一次决策都能回看。</p>
        <div class="entry-story__subjects"><span>社区建模</span><span>协同演练</span><span>决策复盘</span></div>
      </div>
    </section>
  </main>
</template>

<style scoped>
.route-state { min-height:100dvh; display:flex; flex-direction:column; justify-content:center; align-items:center; gap:1rem; padding:2rem; background:var(--surface-page,#f3f1e9); color:var(--text-primary,#173f3e); text-align:center }
.route-state h1 { font-size:1.6rem; margin:0 }
.route-state>div { display:flex; flex-wrap:wrap; gap:1rem }
</style>
