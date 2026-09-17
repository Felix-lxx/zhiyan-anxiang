<script setup lang="ts">
import type { DrillEvent, DrillTask, Resident, Simulation, Robot, Drill, BranchComparison, SpatialIntent, SpatialPreview } from '../domain/drill'
import { createApiClient } from '../api/client'
import { useRoute, useRouter } from 'vue-router'

import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { Community } from '../domain/models'
import DigitalTwinArena from './DigitalTwinArena.vue'
import AppIcon from './AppIcon.vue'
import TaskWorkflow from './TaskWorkflow.vue'
import GuidedExercise from './GuidedExercise.vue'
import SpatialTrainingLab from './SpatialTrainingLab.vue'
import SceneAssistant, { type AssistantAction } from './SceneAssistant.vue'
import DirectorTopbar from './DirectorTopbar.vue'
import DirectorDock from './DirectorDock.vue'
import UiDrawer from './ui/UiDrawer.vue'
import UiToast from './ui/UiToast.vue'
import UiConfirmDialog from './ui/UiConfirmDialog.vue'
import UiSelect from './ui/UiSelect.vue'
import '../director.css'
import '../director-layout.css'

interface Scene { id: string; name: string; status: string }

const props = defineProps<{ apiBaseUrl: string; accessToken: string; community: Community }>()
const api = createApiClient(props.apiBaseUrl, () => props.accessToken)
const route = useRoute(), router = useRouter()
const emit = defineEmits<{ back: []; participant: [] }>()
const scenes = ref<Scene[]>([]), drills = ref<Drill[]>([])
const selectedSceneId = ref(''), current = ref<Drill | null>(null)
const loading = ref(true), busy = ref(false), isPreparingDemo = ref(false)
const autoStartAttempted = ref(false)
const error = ref(''), form = ref({ name: '安巷社区夜间充电棚火灾演练', time_scale: 1 })
type DirectorDrawerName = 'none' | 'missions' | 'events' | 'branches' | 'report' | 'more' | 'participant' | 'settings'
const drawer = ref<DirectorDrawerName>('none')
const branchComparison = ref<BranchComparison | null>(null)
const branchForm = ref({ baseline_strategy: 'south_standard', alternative_strategy: 'north_priority' })
const branchOrigin = ref<number | null>(null)
const showParallel = ref(false), soundEnabled = ref(false), effectsEnabled = ref(true)
const guideOpen = ref(false)
const assistantOpen = ref(false)
const coachOpen = ref(localStorage.getItem('zhiyan_coach_collapsed') === '0')
const detailPanelOpen = computed(() => drawer.value !== 'none' || assistantOpen.value || guideOpen.value)
const coachVisible = computed(() => coachOpen.value && !detailPanelOpen.value)
const endConfirmationOpen = ref(false)
const trainingLab = ref<InstanceType<typeof SpatialTrainingLab> | null>(null)
const routePreview = ref<Array<Resident>>([])
const spatialPreview = ref<SpatialPreview | null>(null)
const spatialPreviewBusy = ref(false)
let spatialPreviewRequest = 0
const branchEvidence = ref<{at_seconds:number;source_name:string;branch_name:string;notice:string;worlds:{baseline:Simulation;alternative:Simulation};residents:Array<{id:string;label:string;original_status:string;branch_status:string;exposure_delta:number;queue_delta:number}>}|null>(null)
function updateFromLab(value: unknown) { current.value = value as Drill; latestCue.value = '指令已写入现场：人员将按楼内通道容量、排队与会合规则连续移动'; clearSpatialPreview() }
function forkFromLab(value: unknown) { const drill=value as Drill; drills.value=[drill,...drills.value]; selectDrill(drill); latestCue.value='已创建历史分支。点击继续训练，再选择另一条路线。' }
async function compareEditable() { if(!current.value)return; try { branchEvidence.value=await api.request(`${props.apiBaseUrl}/drills/${current.value.id}/branch-comparison`, {headers:headers()}) } catch(cause) { error.value=cause instanceof Error?cause.message:'比较失败' } }
const latestCue = ref('等待导演指令'), socketState = ref<'connecting' | 'live' | 'stale'>('connecting')
const participantInvite = ref<{ drill_id: string; code: string; name: string; lan_addresses?: string[] } | null>(null)
const participantOrigin = ref(location.origin)
const arena = ref<InstanceType<typeof DigitalTwinArena> | null>(null)
const highContrast = ref(localStorage.getItem('zhiyan_high_contrast') !== '0'), cameraEnabled = ref(false)
const replay = ref<{ simulation: Simulation; robot: Robot | null; events: DrillEvent[]; tasks: DrillTask[]; at_seconds: number } | null>(null)
const replayAt = ref(0), replayPlaying = ref(false), replayLoading = ref(false)
let replayTimer: number | null = null, replayRequest = 0
const displayed = computed(() => current.value ? replay.value ? { ...current.value, ...replay.value, elapsed_seconds: replay.value.at_seconds } : current.value : null)
const unresolved = computed(() => displayed.value?.simulation.residents.filter(p => p.status !== 'evacuated') ?? [])
const activeTaskCount = computed(() => displayed.value?.tasks.filter(task => task.status !== 'completed').length ?? 0)
const drawerTitle = computed(() => ({ none: '现场工具', missions: '处置任务', events: '事件证据', branches: '比较另一种决策', report: '本场复盘', more: '更多现场工具', participant: '手机参演', settings: '场次与显示' } satisfies Record<DirectorDrawerName, string>)[drawer.value])
const displayClock = computed(() => formatClock(displayed.value?.elapsed_seconds ?? 0))
function formatClock(value: number): string { return `${String(Math.floor(value / 60)).padStart(2,'0')}:${String(value % 60).padStart(2,'0')}` }
let socket: WebSocket | null = null, reconnectTimer: number | null = null, directorTimer: number | null = null, parallelTimer: number | null = null, desiredDrillId = ''
let audioContext: AudioContext | null = null

const publishedScenes = computed(() => scenes.value.filter((scene) => scene.status === 'published'))
const sceneOptions = computed(() => publishedScenes.value.map(scene => ({ value: scene.id, label: scene.name })))
const drillOptions = computed(() => drills.value.map(drill => ({ value: drill.id, label: drill.name })))
const statusLabel = computed(() => ({ ready: '候场', running: '推演中', paused: '已暂停', ended: '已结束' }[current.value?.status ?? ''] ?? '未连接'))
const canBroadcast = computed(() => ['arrived', 'completed'].includes(current.value?.robot?.state ?? ''))
const participantLink = computed(() => participantInvite.value ? `${participantOrigin.value.replace(/\/$/, '')}/participant/${encodeURIComponent(participantInvite.value.drill_id)}?code=${encodeURIComponent(participantInvite.value.code)}` : '')
const headers = (): HeadersInit => ({ Authorization: `Bearer ${props.accessToken}` })

async function loadScenes(): Promise<void> {
  loading.value = true; error.value = ''
  try { scenes.value = await api.request<Scene[]>(`${props.apiBaseUrl}/communities/${props.community.id}/scenes`, { headers: headers() }); const first = publishedScenes.value.find(scene=>scene.id===route.query.scene) ?? publishedScenes.value[0]; if (first) selectedSceneId.value = first.id }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '场景加载失败。' } finally { loading.value = false }
}
async function prepareThreeDemo(): Promise<void> { isPreparingDemo.value = true; try { await api.request(`${props.apiBaseUrl}/communities/demo-ready`, { method: 'POST', headers: headers() }); await loadScenes() } catch (cause) { error.value = cause instanceof Error ? cause.message : '三维演练初始化失败。' } finally { isPreparingDemo.value = false } }
async function loadDrills(): Promise<void> {
  if (!selectedSceneId.value) return
  try {
    drills.value = await api.request<Drill[]>(`${props.apiBaseUrl}/scenes/${selectedSceneId.value}/drills`, { headers: headers() })
    if (drills.value[0]) selectDrill(drills.value.find((item) => item.id === route.query.drill) ?? drills.value[0])
    else {
      current.value = null; desiredDrillId = ''; socket?.close()
      if (route.query.autostart === '1' && !autoStartAttempted.value) {
        autoStartAttempted.value = true
        await createDrill()
      }
    }
  }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '演练场次加载失败。' }
}
async function createDrill(): Promise<void> { busy.value = true; try { const drill = await api.request<Drill>(`${props.apiBaseUrl}/scenes/${selectedSceneId.value}/drills`, { method: 'POST', headers: { ...headers(), 'Content-Type': 'application/json' }, body: JSON.stringify(form.value) }); drills.value = [drill, ...drills.value]; selectDrill(drill) } catch (cause) { error.value = cause instanceof Error ? cause.message : '场次创建失败。' } finally { busy.value = false } }
function selectDrill(drill: Drill): void { leaveReplay(); clearSpatialPreview(); branchEvidence.value=null; current.value = drill; branchComparison.value = null; showParallel.value = false; drawer.value = 'none'; void router.replace({query:{scene:selectedSceneId.value,drill:drill.id}}); connectSocket(drill.id); void loadParticipantInvite() }
async function loadParticipantInvite(): Promise<void> { if (!current.value) return; try { const invite = await api.request<{ drill_id: string; code: string; name: string; lan_addresses?: string[] }>(`${props.apiBaseUrl}/drills/${current.value.id}/participant-invite`, { headers: headers() }); participantInvite.value = invite; if (['127.0.0.1', 'localhost'].includes(location.hostname) && invite.lan_addresses?.[0]) participantOrigin.value = `http://${invite.lan_addresses[0]}:${location.port || '5173'}` } catch { participantInvite.value = null } }
async function copyParticipantLink(): Promise<void> { if (!participantLink.value) return; try { await navigator.clipboard.writeText(participantLink.value); latestCue.value = '参演链接已复制，可在手机浏览器直接打开' } catch { error.value = '当前浏览器未开放剪贴板权限，请选中上方完整参演链接并手动复制。' } }
function connectSocket(drillId: string): void {
  desiredDrillId = drillId; socket?.close(); if (reconnectTimer) window.clearTimeout(reconnectTimer); socketState.value = 'connecting'
  socket = new WebSocket(api.websocketUrl(`/api/v1/ws/drills/${drillId}?token=${encodeURIComponent(props.accessToken)}`))
  socket.onopen = () => { socketState.value = 'live' }; socket.onmessage = (event) => { if(desiredDrillId!==drillId)return; const message = JSON.parse(event.data) as { type: string; data: Drill }; if (message.type === 'drill.snapshot') current.value = message.data }; socket.onerror = () => { socketState.value = 'stale' }
  socket.onclose = () => { socketState.value = 'stale'; if (desiredDrillId === drillId) reconnectTimer = window.setTimeout(() => connectSocket(drillId), 1800) }
}
async function requestDrill(path: string, method: 'POST' | 'PATCH', body?: unknown, successMessage?: string): Promise<void> {
  if (!current.value || busy.value) return; busy.value = true; error.value = ''
  try { current.value = await api.request<Drill>(`${props.apiBaseUrl}/drills/${current.value.id}${path}`, { method, headers: { ...headers(), ...(body ? { 'Content-Type': 'application/json' } : {}) }, body: body ? JSON.stringify(body) : undefined }); if (successMessage) latestCue.value = successMessage }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '现场操作失败。' } finally { busy.value = false }
}
async function act(action: 'start' | 'pause' | 'resume' | 'end'): Promise<void> {
  if (action === 'end') { endConfirmationOpen.value = true; return }
  leaveReplay(); await requestDrill('/state', 'PATCH', { action }, action === 'start' ? '演练时钟已启动，机器人开始自动巡检；现场状态将每秒更新' : action === 'pause' ? '演练已暂停，人员与车辆保持当前位置' : '演练已继续，人员与车辆恢复移动')
}
async function confirmEnd(): Promise<void> { leaveReplay(); await requestDrill('/state', 'PATCH', { action: 'end' }); if (!error.value) { endConfirmationOpen.value = false; drawer.value = 'report' } }
async function inject(event_type: 'channel_blocked' | 'hydrant_failure' | 'resident_missing', context: { x?: number; y?: number; target?: string; road_edge_id?: string } = {}): Promise<void> { await requestDrill('/inject', 'POST', { event_type, ...context }, '扰动已写入现场，路线、人员与评分证据正在同步更新') }
async function robot(command: 'step' | 'broadcast' | 'replan'): Promise<void> { await requestDrill('/robot', 'POST', { command }, command === 'broadcast' ? '广播已执行，楼内居民开始准备并依次下楼' : command === 'replan' ? '机器人已按当前风险路网重新规划路线' : '机器人已推进到下一段路线') }
async function cancelRobotTask(taskId: string): Promise<void> { await requestDrill('/robot', 'POST', { command: 'cancel', task_id: taskId }, '排队任务已取消，当前正在执行的任务不受影响') }
async function moveRobot(context: { x: number; y: number; target: string }): Promise<void> { await requestDrill('/robot', 'POST', { command: 'move', ...context }, `指令已接收：机器人正前往${context.target}，到达前不能执行目标点任务`) }
function clearSpatialPreview(): void {
  spatialPreviewRequest += 1
  spatialPreview.value = null
  routePreview.value = []
  spatialPreviewBusy.value = false
}
async function previewSpatialAction(intent: SpatialIntent): Promise<void> {
  if (!current.value || current.value.status !== 'running' || replay.value) return
  closeFloatingPanels()
  const request = ++spatialPreviewRequest
  spatialPreviewBusy.value = true; error.value = ''; spatialPreview.value = null; routePreview.value = []
  try {
    let value: Omit<SpatialPreview, 'intent'>
    if (intent.kind === 'road') value = await api.request(`${props.apiBaseUrl}/drills/${current.value.id}/roads/${intent.edgeId}/preview-block`, { headers: headers() })
    else if (intent.kind === 'robot') value = await api.request(`${props.apiBaseUrl}/drills/${current.value.id}/robot/preview`, { method: 'POST', headers: { ...headers(), 'Content-Type': 'application/json' }, body: JSON.stringify({ command: 'move', x: intent.x, y: intent.y, target: intent.target }) })
    else value = await api.request(`${props.apiBaseUrl}/drills/${current.value.id}/residents/preview`, { method: 'POST', headers: { ...headers(), 'Content-Type': 'application/json' }, body: JSON.stringify({ resident_ids: intent.residentIds, exit: intent.exit, action: intent.action }) })
    if (request !== spatialPreviewRequest) return
    spatialPreview.value = { ...value, intent }
    if (value.kind === 'residents') routePreview.value = value.residents ?? []
    latestCue.value = value.can_apply ? '预演完成：虚线路线尚未执行，请核对影响后确认' : '预演发现目标不可达，请调整对象或解除封锁'
  } catch (cause) {
    if (request === spatialPreviewRequest) error.value = cause instanceof Error ? cause.message : '空间操作预演失败。'
  } finally { if (request === spatialPreviewRequest) spatialPreviewBusy.value = false }
}
async function confirmSpatialAction(): Promise<void> {
  const preview = spatialPreview.value
  if (!preview?.can_apply || !current.value || busy.value) return
  const intent = preview.intent
  if (intent.kind === 'road') await requestDrill('/inject', 'POST', { event_type: 'channel_blocked', road_edge_id: intent.edgeId })
  else if (intent.kind === 'robot') await requestDrill('/robot', 'POST', { command: 'move', x: intent.x, y: intent.y, target: intent.target })
  else await requestDrill('/residents', 'POST', { resident_ids: intent.residentIds, exit: intent.exit, action: intent.action })
  if (!error.value) {
    latestCue.value = intent.kind === 'road' ? '道路封锁已写入证据，居民与机器人正在按新路网改道' : intent.kind === 'robot' ? '机器人任务已加入动态队列，正在沿 A* 路线逐段执行' : '居民指令已生效，正在按楼内容量与排队规则连续移动'
    clearSpatialPreview()
  }
}
async function commandResidents(context: { residentIds: string[]; exit: 'north' | 'south'; action: 'evacuate' | 'priority_assist' }): Promise<void> {
  if ((current.value?.engine_version ?? 1) >= 3) { coachOpen.value=true; await nextTick(); await trainingLab.value?.previewCommand(context); return }
  await requestDrill('/residents', 'POST', { resident_ids: context.residentIds, exit: context.exit, action: context.action })
}
async function taskAction(taskId: string, action: 'accept' | 'arrive' | 'submit', evidence: string): Promise<void> { const label = action === 'accept' ? '任务已接收，请到目标点后回执到位' : action === 'arrive' ? '到位回执已记录，请提交处置证据' : '处置证据已核验，现场影响和过程评分已更新'; await requestDrill(`/tasks/${taskId}/actions`, 'POST', { action, evidence }, label) }
function locateTask(task: DrillTask): void { drawer.value = 'none'; if (task.target_position) arena.value?.focusPoint(task.target_position.x, task.target_position.y) }
async function dispatchTask(task: DrillTask): Promise<void> { if (task.target_position) await moveRobot({ ...task.target_position, target: task.title }) }
async function reopenRoad(id: string): Promise<void> { await requestDrill(`/roads/${id}/reopen`, 'POST', undefined, '道路已恢复通行，人员与机器人从当前位置重新规划') }
async function configureDirector(event: Event): Promise<void> { await requestDrill('/director/config', 'PATCH', { enabled: (event.target as HTMLInputElement).checked }) }
async function seekReplay(at: number): Promise<void> {
  if (!current.value) return
  const request = ++replayRequest, drillId = current.value.id
  replayAt.value = Math.max(0, Math.min(current.value.elapsed_seconds, at)); replayLoading.value = true
  try {
    const value = await api.request<NonNullable<typeof replay.value>>(`${props.apiBaseUrl}/drills/${drillId}/replay?at_seconds=${replayAt.value}`, { headers: headers() })
    if (request === replayRequest && current.value?.id === drillId) replay.value = value
  } catch (cause) { if (request === replayRequest) { error.value = cause instanceof Error ? cause.message : '回放加载失败，请重试'; replayPlaying.value = false } }
  finally { if (request === replayRequest) replayLoading.value = false }
}
function leaveReplay(): void { replayRequest++; replay.value = null; replayPlaying.value = false; replayLoading.value = false }
function changeDrill(event: Event): void { const drill = drills.value.find(d => d.id === (event.target as HTMLSelectElement).value); if (drill) selectDrill(drill) }
function onEscape(event: KeyboardEvent): void { if (event.key === 'Escape') { closeFloatingPanels(); showParallel.value = false } }
async function compareBranches(): Promise<void> {
  if (!current.value) return; busy.value = true
  branchOrigin.value = replay.value?.at_seconds ?? null
  try { branchComparison.value = await api.request<BranchComparison>(`${props.apiBaseUrl}/drills/${current.value.id}/branches/compare`, { method: 'POST', headers: { ...headers(), 'Content-Type': 'application/json' }, body: JSON.stringify({ ...branchForm.value, at_seconds: branchOrigin.value }) }); showParallel.value = true; drawer.value = 'none' }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '平行方案推演失败。' } finally { busy.value = false }
}
async function refreshBranchWorlds(): Promise<void> { if (!current.value || !showParallel.value) return; try { branchComparison.value = await api.request<BranchComparison>(`${props.apiBaseUrl}/drills/${current.value.id}/branches/compare`, { method: 'POST', headers: { ...headers(), 'Content-Type': 'application/json' }, body: JSON.stringify({ ...branchForm.value, at_seconds: branchOrigin.value }) }) } catch { /* keep last valid worlds during transient reconnect */ } }
async function downloadReport(): Promise<void> {
  if (!current.value) return
  try { const report = await api.request<Record<string, unknown>>(`${props.apiBaseUrl}/drills/${current.value.id}/report`, { headers: headers() }); const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json;charset=utf-8' }); const url = URL.createObjectURL(blob), anchor = document.createElement('a'); anchor.href = url; anchor.download = `${current.value.name}-复盘报告.json`; anchor.click(); URL.revokeObjectURL(url) }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '请先结束演练并生成评分。' }
}
function closeFloatingPanels(): void { drawer.value = 'none'; guideOpen.value = false; assistantOpen.value = false; clearSpatialPreview() }
function toggleAssistant(): void { const next = !assistantOpen.value; closeFloatingPanels(); assistantOpen.value = next }
function closeAssistant(): void { assistantOpen.value = false; void nextTick(() => document.querySelector<HTMLButtonElement>('.director-rail button:last-child')?.focus()) }
async function assistantNavigate(action: AssistantAction): Promise<void> {
  closeFloatingPanels()
  if (action.kind === 'focus' && action.resident_id) { arena.value?.focusResident(action.resident_id); return }
  if (['missions', 'events', 'report'].includes(action.kind)) { drawer.value = action.kind as 'missions' | 'events' | 'report'; return }
  if (['command', 'rollcall', 'branch'].includes(action.kind)) { coachOpen.value = true; await nextTick(); trainingLab.value?.openTab(action.kind as 'command' | 'rollcall' | 'branch'); document.querySelector(trainingLab.value ? '.spatial-lab' : '.training-upgrade')?.scrollIntoView({ block: 'nearest', behavior: 'instant' }) }
}
function toggleDrawer(value: DirectorDrawerName): void { const next = drawer.value === value ? 'none' : value; closeFloatingPanels(); drawer.value = next }
function toggleInvite(): void { toggleDrawer('participant') }
function toggleControls(): void { toggleDrawer('settings') }
function toggleGuide(): void { const next = !guideOpen.value; closeFloatingPanels(); guideOpen.value = next }
function closeGuide(): void { guideOpen.value = false; localStorage.setItem('zhiyan_director_guide_seen', '1') }
function toggleCoach(): void { coachOpen.value = !coachVisible.value; localStorage.setItem('zhiyan_coach_collapsed', coachOpen.value ? '0' : '1'); closeFloatingPanels() }
function toggleSound(): void { soundEnabled.value = !soundEnabled.value; if (soundEnabled.value) audioContext ??= new AudioContext(); latestCue.value = soundEnabled.value ? '声音与语音提示已启用' : '声音提示已关闭' }
function playCue(event: DrillEvent): void {
  latestCue.value = event.message; if (!soundEnabled.value || !audioContext) return
  const oscillator = audioContext.createOscillator(), gain = audioContext.createGain(); oscillator.type = event.event_type.startsWith('inject.') ? 'sawtooth' : 'sine'; oscillator.frequency.value = event.event_type.startsWith('inject.') ? 620 : 420; gain.gain.setValueAtTime(.0001, audioContext.currentTime); gain.gain.exponentialRampToValueAtTime(.08, audioContext.currentTime + .03); gain.gain.exponentialRampToValueAtTime(.0001, audioContext.currentTime + .48); oscillator.connect(gain).connect(audioContext.destination); oscillator.start(); oscillator.stop(audioContext.currentTime + .5)
  if ('speechSynthesis' in window && event.event_type.startsWith('inject.')) { window.speechSynthesis.cancel(); window.speechSynthesis.speak(new SpeechSynthesisUtterance(event.message)) }
}

watch(selectedSceneId, () => { desiredDrillId = ''; current.value = null; socket?.close(); void loadDrills() })
watch(() => current.value?.events[0]?.sequence, () => { const event = current.value?.events[0]; if (event) playCue(event) })
watch(highContrast, value => localStorage.setItem('zhiyan_high_contrast', value ? '1' : '0'))
watch(replayPlaying, playing => { if (replayTimer) window.clearInterval(replayTimer); replayTimer = playing ? window.setInterval(() => { if (replayLoading.value) return; if (replayAt.value >= (current.value?.elapsed_seconds ?? 0)) { replayPlaying.value = false; return }; void seekReplay(replayAt.value + 1) }, 1000) : null })
watch(showParallel, (visible) => { if (parallelTimer) window.clearInterval(parallelTimer); parallelTimer = visible ? window.setInterval(() => void refreshBranchWorlds(), 3000) : null })
onMounted(() => { void loadScenes(); document.addEventListener('keydown', onEscape) })
onBeforeUnmount(() => { document.removeEventListener('keydown', onEscape); if (replayTimer) window.clearInterval(replayTimer); replayRequest++ })
onBeforeUnmount(() => { desiredDrillId = ''; socket?.close(); if (reconnectTimer) window.clearTimeout(reconnectTimer); if (directorTimer) window.clearInterval(directorTimer); if (parallelTimer) window.clearInterval(parallelTimer); void audioContext?.close() })
</script>

<template>
  <main id="main-content" class="operations-center operations-center--immersive" data-ui-theme="immersive" :class="{ 'coach-open': coachVisible, 'detail-panel-open': detailPanelOpen, 'assistant-open': assistantOpen, 'space-preview-open': spatialPreviewBusy || Boolean(spatialPreview) }" :data-replay="Boolean(replay)">
    <UiToast v-if="error && !current" :message="error" tone="danger" action-label="重新加载" :dismissible="false" @action="loadScenes" />
    <section v-if="loading" class="immersive-loading">正在装载社区数字孪生现场…</section>
    <section v-else-if="publishedScenes.length === 0" class="operations-empty operations-empty--immersive"><h1>准备三维演练现场</h1><p>先创建已发布场景，或使用充电棚火灾主案例。</p><button class="primary-button" type="button" :disabled="isPreparingDemo" @click="prepareThreeDemo">{{ isPreparingDemo ? '正在构建…' : '准备主案例' }}</button><button type="button" @click="emit('back')">返回项目</button></section>
    <section v-else-if="!current" class="operations-empty operations-empty--immersive"><span>导演台 · 场次准备</span><h1>新建演练场次</h1><p>先选择已发布场景，再冻结一份可运行的社区与人员配置；从项目页进入时会自动准备第一场。</p><div class="immersive-create"><label><span>运行场景</span><select v-model="selectedSceneId"><option v-for="scene in publishedScenes" :key="scene.id" :value="scene.id">{{ scene.name }}</option></select></label><label><span>场次名称</span><input v-model="form.name" maxlength="160" placeholder="例如：夜间充电棚火灾 · 第一轮" /></label><button class="primary-button" type="button" :disabled="busy" @click="createDrill">进入三维导演台</button></div></section>
    <template v-else-if="displayed">
      <DirectorTopbar :name="current.name" :subtitle="(current.engine_version ?? 1) >= 2 ? '场景配置已冻结 · 三维现场实时运行' : '历史场次 · 固定主案例模型'" :socket-state="socketState" :status-label="statusLabel" :display-clock="displayClock" :drill-status="current.status" :busy="busy" :coach-open="coachVisible" :replay="Boolean(replay)" @back="emit('back')" @toggle-coach="toggleCoach" @action="act" @create="createDrill" />
      <section class="director-stage">
        <SceneAssistant :key="current.id" :open="assistantOpen" :api-base-url="apiBaseUrl" :access-token="accessToken" :drill-id="current.id" :drill-name="current.name" :live-seconds="current.elapsed_seconds" :at-seconds="replay?.at_seconds ?? null" @close="closeAssistant" @navigate="assistantNavigate" />
        <GuidedExercise v-if="coachOpen" :drill="displayed" :busy="busy" :replay="Boolean(replay)" @indoor="arena?.showIndoor()" @start="act('start')" @resume="act('resume')" @finish="act('end')" @retry="createDrill" @live="leaveReplay" @tasks="toggleDrawer('missions')" @compare="toggleDrawer('branches')" @dispatch="dispatchTask" @locate="locateTask" @broadcast="robot('broadcast')" @assist="ids => commandResidents({ residentIds: ids, exit: 'north', action: 'priority_assist' })" @evacuate="(ids, exit) => commandResidents({ residentIds: ids, exit, action: 'evacuate' })" @focus="id => arena?.focusResident(id)" @task="taskAction" @block="id => inject('channel_blocked', { road_edge_id: id })" @reopen="reopenRoad" @seek="seekReplay"><SpatialTrainingLab v-if="(current.engine_version ?? 1) >= 3" ref="trainingLab" :drill="displayed" :api-base-url="apiBaseUrl" :access-token="accessToken" :replay="Boolean(replay)" @updated="updateFromLab" @forked="forkFromLab" @select="ids => arena?.selectResidents(ids)" @preview="people => routePreview = people as Resident[]" @focus="id => arena?.focusResident(id)" @compare="compareEditable" /><section v-else class="training-upgrade"><h2>当前场次使用历史模型</h2><p>新建连续空间训练，启用楼内行走、路线预览、集合核验与历史重做；原场次不会删除或改写。</p><button :disabled="busy" @click="createDrill">新建连续空间训练</button></section></GuidedExercise>
        <DigitalTwinArena :key="current.id" ref="arena" :route-preview="routePreview" :robot-route-preview="spatialPreview?.kind === 'robot' ? spatialPreview.route_points : []" :operation-preview="spatialPreview" :operation-busy="spatialPreviewBusy || Boolean(spatialPreview && busy)" @selection="ids => trainingLab?.selectIds(ids)" :status="replay ? 'paused' : current.status" :elapsed-seconds="displayed.elapsed_seconds" :robot="displayed.robot" :simulation="displayed.simulation" :events="displayed.events" :interactive="!replay && current.status === 'running' && !busy" :effects-enabled="effectsEnabled" :camera-enabled="cameraEnabled && !replay" :high-contrast="highContrast" @inject="inject" @robot-command="robot" @preview-action="previewSpatialAction" @confirm-action="confirmSpatialAction" @cancel-action="clearSpatialPreview" @reopen-road="reopenRoad" />
        <aside class="director-metrics" aria-label="现场关键态势">
          <div><span>火势指数</span><strong>{{ displayed.simulation.fire.intensity }}</strong></div>
          <div><span>烟气暴露</span><strong>{{ displayed.simulation.summary.smoke_exposed ?? 0 }}<small>人</small></strong></div>
          <div><span>已疏散</span><strong>{{ displayed.simulation.summary.evacuated }}<small>/{{ displayed.simulation.summary.total }}</small></strong></div>
          <button class="locate-unresolved" type="button" :disabled="!unresolved.length" @click="arena?.focusResident(unresolved.find(p => p.status === 'missing')?.id ?? unresolved[0]!.id)"><AppIcon name="target" /><span>{{ unresolved.length ? '定位未撤离 ' + unresolved.length + ' 人' : '全部到达集合点' }}</span></button>
        </aside>
        <DirectorDock :active="assistantOpen ? 'more' : drawer" :task-count="activeTaskCount" :event-count="displayed.events.length" :score="(current.score ?? current.score_preview).total_score" @open="toggleDrawer" />
        <div class="director-intelligence" role="status"><strong>{{ replay ? '历史过程只读；拖动底部时间轴查看当时的道路、人员和任务' : current.status === 'ended' ? '本场已结束。查看评分证据，或从底部回放关键过程。' : latestCue }}</strong></div>
        <UiDrawer v-if="drawer !== 'none'" :key="drawer" class="director-drawer" :title="drawerTitle" :subtitle="replay ? '历史时刻 ' + displayClock : '与当前场次实时联动'" @close="drawer = 'none'">
          <div v-if="drawer === 'missions'" class="drawer-list">
            <article v-if="displayed.robot" class="robot-mission"><h3>巡检广播机器人</h3><p>{{ displayed.robot.reason }}</p><p>{{ displayed.robot.route.join(' → ') }}</p>
              <ol class="robot-task-queue"><li v-for="item in displayed.robot.task_queue" :key="item.id"><strong>{{ item.label }}</strong><span>{{ { executing: '移动中', queued: '排队等待', blocked: '无法到达', completed: '已到达', cancelled: '已取消' }[item.status] ?? item.status }}</span><progress :value="item.progress" max="1" :aria-label="item.label + '进度'"></progress><small>{{ item.route_edge_ids.length }} 个道路段 · {{ Math.round(item.progress * 100) }}%</small><button v-if="!replay && ['executing','queued','blocked'].includes(item.status)" type="button" :disabled="busy || current.status !== 'running'" @click="cancelRobotTask(item.id)">取消任务</button></li></ol>
              <div v-if="!replay"><button type="button" :disabled="busy || current.status !== 'running'" @click="robot('replan')">重算风险路径</button><button type="button" :disabled="busy || current.status !== 'running' || !canBroadcast" @click="robot('broadcast')">{{ canBroadcast ? '在此执行广播' : '等待机器人到达' }}</button></div>
            </article>
            <TaskWorkflow v-for="task in displayed.tasks" :key="task.id" :task="task" :running="!replay && current.status === 'running'" :readonly="Boolean(replay)" :busy="busy" director @action="(action, evidence) => taskAction(task.id, action, evidence)" @locate="locateTask(task)" @dispatch="dispatchTask(task)" />
            <p v-if="!displayed.tasks.length">此时尚无已触发任务。</p>
          </div>
          <ol v-else-if="drawer === 'events'" class="director-event-list"><li v-for="event in displayed.events" :key="event.id"><button type="button" :aria-label="'回放 ' + formatClock(event.elapsed_seconds) + event.message" @click="seekReplay(event.elapsed_seconds)"><time :datetime="`PT${event.elapsed_seconds}S`">{{ formatClock(event.elapsed_seconds) }}</time></button><div><strong>{{ event.message }}</strong><span>{{ event.actor }}</span><small v-if="event.payload?.blocked_edge_id">道路：{{ event.payload.blocked_edge_name }}</small><small v-if="event.payload?.impact">预计 30 秒后：拥堵 {{ event.payload.impact.congested_before }}→{{ event.payload.impact.congested_after }}，暴露 {{ event.payload.impact.smoke_exposed_before }}→{{ event.payload.impact.smoke_exposed_after }}</small></div></li></ol>
          <div v-else-if="drawer === 'branches'" class="branch-launcher"><button v-if="current.branch" @click="compareEditable">查看本分支与原训练的实际差异</button><p>从同一历史时刻比较三种既定疏散策略。此功能是规则预测，不是独立可编辑世界。</p><label>方案 A<select v-model="branchForm.baseline_strategy"><option value="south_standard">南门常规疏散</option><option value="north_priority">北门重点优先</option><option value="dual_exit">双出口分流</option></select></label><label>方案 B<select v-model="branchForm.alternative_strategy"><option value="north_priority">北门重点优先</option><option value="dual_exit">双出口分流</option><option value="south_standard">南门常规疏散</option></select></label><button type="button" :disabled="busy || branchForm.baseline_strategy === branchForm.alternative_strategy" @click="compareBranches">查看两种结果</button></div>
          <div v-else-if="drawer === 'report'" class="score-drawer"><strong>{{ (current.score ?? current.score_preview).total_score }}</strong><span>/ 100 · {{ current.score ? '最终得分' : '当前过程评分' }}</span><p>{{ (current.engine_version ?? 1) >= 2 ? '按疏散结果、人员风险、核验任务与响应时效计分；不按点击次数加分。' : '历史版本评分，保留当时的统计口径。新开一轮使用场景驱动模型。' }}</p><ol><li v-for="item in (current.score ?? current.score_preview).details" :key="item.name"><div><span>{{ item.name }}</span><b>{{ item.score }}/{{ item.max_score ?? '—' }}</b></div><progress v-if="item.max_score" :value="item.score" :max="item.max_score" :aria-label="item.name + '得分'"></progress><small>{{ item.evidence }}</small><button v-if="item.at_seconds !== undefined" type="button" @click="seekReplay(item.at_seconds)">回到相关事件</button></li></ol><button type="button" @click="seekReplay(0)">从头回放本场</button><button type="button" :disabled="!current.score" @click="downloadReport">导出证据报告</button></div>
          <nav v-else-if="drawer === 'more'" class="director-more-menu" aria-label="更多现场工具">
            <button id="open-scene-assistant" type="button" @click="toggleAssistant"><AppIcon name="brain" /><span><strong>安巷 AI 教练</strong><small>结合当前现场解释下一步处置</small></span><AppIcon name="arrowRight" /></button>
            <button type="button" @click="toggleDrawer('branches')"><AppIcon name="split" /><span><strong>双世界决策对比</strong><small>从同一时刻比较另一种选择</small></span><AppIcon name="arrowRight" /></button>
            <button type="button" @click="toggleInvite"><AppIcon name="phone" /><span><strong>手机参演</strong><small>邀请居民与处置角色实时回执</small></span><AppIcon name="arrowRight" /></button>
            <button type="button" @click="toggleControls"><AppIcon name="settings" /><span><strong>场次与显示</strong><small>自动导演、声音、灯光与镜头</small></span><AppIcon name="arrowRight" /></button>
            <button type="button" @click="toggleGuide"><AppIcon name="help" /><span><strong>操作指引</strong><small>用四步完成一次可复盘处置</small></span><AppIcon name="arrowRight" /></button>
          </nav>
          <div v-else-if="drawer === 'participant' && participantInvite" class="participant-invite participant-invite--embedded"><p>同一局域网打开链接，登记姓名与角色。身份绑定当前设备，任务按责任分配。</p><strong>{{ participantInvite.code }}</strong><label>电脑访问地址<input v-model="participantOrigin" /></label><input :value="participantLink" readonly aria-label="完整参演链接" /><div><button type="button" @click="copyParticipantLink">复制链接</button><button type="button" @click="emit('participant')">本机预览</button></div><p>以下是角色反馈记录，不代表设备在线人数。</p><ul class="participant-presence"><li v-for="participant in current.participants" :key="participant.role"><div><strong>{{ participant.role }}</strong><small>{{ participant.status ?? '等待反馈' }}</small></div></li></ul></div>
          <div v-else-if="drawer === 'settings'" class="scene-control-popover scene-control-popover--embedded">
          <UiSelect v-model="selectedSceneId" label="当前场景" :options="sceneOptions" hint="切换场景后载入对应的历史场次" />
          <UiSelect :model-value="current.id" label="历史场次" :options="drillOptions" @change="changeDrill" @update:model-value="() => undefined" />
          <label><span><strong>自动事件导演</strong><small>会写入扰动事件；后台运行，关闭页面仍继续</small></span><input type="checkbox" :checked="current.director_enabled" :disabled="busy || current.status === 'ended'" @change="configureDirector" /></label>
          <label><span><strong>高对比态势</strong><small>提升道路与人员辨识度</small></span><input v-model="highContrast" type="checkbox" /></label>
          <label><span><strong>声音提示</strong></span><input :checked="soundEnabled" type="checkbox" @change="toggleSound" /></label>
          <label><span><strong>火场动态灯光</strong></span><input v-model="effectsEnabled" type="checkbox" /></label>
          <label><span><strong>事件镜头跟随</strong></span><input v-model="cameraEnabled" type="checkbox" /></label>
          <button type="button" @click="toggleGuide">查看操作指引</button>
          </div>
        </UiDrawer>
        <aside v-if="guideOpen" class="experience-guide" aria-label="三维导演台使用指引"><button type="button" aria-label="关闭使用指引" @click="closeGuide"><AppIcon name="close" /></button><h2>让一次处置真正改变现场</h2><ol><li><AppIcon name="play" /><div><strong>开始并观察巡检</strong><span>机器人接近起火点，连续采样确认后触发任务。</span></div></li><li><AppIcon name="target" /><div><strong>点击对象，执行处置</strong><span>封锁或开放道路，派机器人，选择居民分流；蓝色护送员会前往会合。</span></div></li><li><AppIcon name="phone" /><div><strong>手机完成责任任务</strong><span>接收、回执到位、填写证据；核验通过才改变现场。</span></div></li><li><AppIcon name="award" /><div><strong>用时间轴检查过程</strong><span>拖动底部时间轴回到任何时刻，或从评分定位事件。</span></div></li></ol><button class="experience-guide__start" type="button" @click="closeGuide">进入现场</button></aside>
        <div class="exercise-timeline">
          <button type="button" :disabled="!current.elapsed_seconds || replayLoading" :aria-label="replayPlaying ? '暂停回放' : '播放回放'" @click="replayPlaying ? replayPlaying = false : (seekReplay(replay ? replayAt : 0), replayPlaying = true)"><AppIcon :name="replayPlaying ? 'pause' : 'play'" /></button>
          <label>历史时间轴<input type="range" min="0" :max="current.elapsed_seconds" :value="replay ? replayAt : current.elapsed_seconds" aria-label="回放时刻（秒）" @input="seekReplay(Number(($event.target as HTMLInputElement).value))" /></label>
          <output aria-live="off">{{ replayLoading ? '读取中' : displayClock }}</output>
          <button v-if="replay" type="button" @click="leaveReplay">{{ current.status === 'ended' ? '回到最终结果' : '返回实时现场' }}</button>
          <span v-else>{{ current.status === 'ended' ? '本场已冻结' : '实时现场' }}</span>
        </div>
        <UiToast v-if="error" :message="error" tone="danger" @dismiss="error = ''" />
        <UiConfirmDialog :open="endConfirmationOpen" title="结束本场并生成评分？" :description="`结束后本场不能继续，当前仍有 ${activeTaskCount} 项任务未完成。系统将冻结现场并生成复盘证据。`" confirm-label="结束并评分" cancel-label="继续演练" :busy="busy" theme="immersive" danger @confirm="confirmEnd" @cancel="endConfirmationOpen = false" />
      </section>
      <section v-if="showParallel && branchComparison" class="parallel-worlds" aria-label="左右双世界三维平行推演"><header><div><h2>同一现场，两种疏散策略</h2><p>向前预测 {{ branchComparison.projection_seconds }} 秒 · 规则仿真</p></div><button type="button" @click="showParallel = false">返回现场</button></header><div class="parallel-worlds__stage"><article v-for="side in (['baseline','alternative'] as const)" :key="side"><DigitalTwinArena :key="current.id + '-' + side" status="running" :elapsed-seconds="branchComparison.at_seconds" :robot="branchComparison.robots[side]" :simulation="branchComparison.worlds[side]" compact :high-contrast="highContrast" :world-label="branchComparison[side].name" /><footer><span>疏散 {{ branchComparison[side].evacuation_seconds === null ? '无法完成' : branchComparison[side].evacuation_seconds + ' 秒' }}</span><span>暴露 {{ branchComparison[side].smoke_exposed }} 人</span><span>不可达 {{ branchComparison[side].unreachable }}</span><strong>{{ branchComparison[side].projected_score }} 分</strong></footer></article></div><div class="parallel-verdict"><strong>{{ branchComparison.recommendation }}</strong><small>{{ branchComparison.disclaimer }}</small></div></section>
      <section v-if="branchEvidence" class="parallel-worlds spatial-comparison" aria-label="历史分支实际结果对比">
        <header><div><h2>同一批居民 · {{ branchEvidence.at_seconds }} 秒</h2><p>{{ branchEvidence.notice }}</p></div><button @click="branchEvidence=null">返回训练</button></header>
        <div class="parallel-worlds__stage"><article v-for="side in (['baseline','alternative'] as const)" :key="side"><DigitalTwinArena :key="current.id+'actual'+side" status="paused" :elapsed-seconds="branchEvidence.at_seconds" :robot="null" :simulation="branchEvidence.worlds[side]" compact :high-contrast="highContrast" :world-label="side==='baseline'?'原训练':'我的新选择'" /><footer>到集合点 {{branchEvidence.worlds[side].summary.evacuated}} 人 · 烟气暴露 {{branchEvidence.worlds[side].summary.smoke_exposed}} 人</footer></article></div>
        <div class="branch-person-results"><table><caption>逐人比较（新选择减去原训练）</caption><thead><tr><th>居民</th><th>原训练</th><th>新选择</th><th>暴露差值</th><th>排队差值 / 秒</th></tr></thead><tbody><tr v-for="p in branchEvidence.residents" :key="p.id"><td>{{p.label}}</td><td>{{p.original_status}}</td><td>{{p.branch_status}}</td><td>{{p.exposure_delta}}</td><td>{{p.queue_delta}}</td></tr></tbody></table></div>
      </section>
    </template>
  </main>
</template>

<style scoped>
.spatial-comparison{overflow:auto}.branch-person-results{max-height:240px;overflow:auto;background:#102e29;padding:16px}.branch-person-results table{width:100%;font-size:13px;border-collapse:collapse}.branch-person-results th,.branch-person-results td{padding:10px;text-align:left;border-bottom:1px solid #426157}.branch-person-results caption{text-align:left;padding:10px;font-weight:600}
</style>
