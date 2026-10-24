<script setup lang="ts">
import { createApiClient } from '../api/client'
import AgentPlanWorkspace from './AgentPlanWorkspace.vue'
import type { AgentAssignment, AgentLiveState } from '../domain/agent'

import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import '../assistant.css'
export type AssistantAction = { kind: 'missions' | 'events' | 'report' | 'command' | 'rollcall' | 'branch' | 'focus' | 'plan' | 'replay' | 'indoor'; label: string; resident_id?: string; door_id?:string; object_kind?:'robot'; at_seconds?:number }
export interface AssistantFocusContext { kind: 'resident' | 'road' | 'robot' | 'object' | 'command' | 'score' | 'replay'; id?: string; label: string; type?: string; detail?: string; x?: number; y?: number }
interface Reply {
  mode: 'offline' | 'model'; model: string | null; answer: string; notice: string
  context: { at_seconds: number; historical: boolean; selection: AssistantFocusContext | null }
  sources: Array<{ id: string; title: string; detail: string }>; actions: AssistantAction[]
}
interface Message { role: 'user' | 'assistant'; content: string; reply?: Reply }
const props = defineProps<{ apiBaseUrl: string; accessToken: string; drillId: string; drillName: string; open: boolean; atSeconds: number | null; liveSeconds: number; drillStatus?: string; busy?: boolean; focusContext?: AssistantFocusContext | null; agentFeed?:AgentLiveState|null;connection?:'connecting'|'live'|'stale' }>()
const api = createApiClient(props.apiBaseUrl, () => props.accessToken)
const emit = defineEmits<{ close: []; navigate: [action: AssistantAction]; planPreview: [people: AgentAssignment[]]; stateAction: [action: 'pause'|'resume'|'end'] }>()
const activeView = ref<'chat' | 'plan'>('chat')
let keepPlanPreview = false
function previewPlan(people: AgentAssignment[]) {
  emit('planPreview', people)
  if (people.length && mobile.value) { keepPlanPreview = true; previousFocus = null; emit('close') }
}
function showSettings() { activeView.value = 'chat'; void toggleHelp('settings') }
const messages = ref<Message[]>([]), question = ref(''), error = ref(''), pending = ref(false)
const provider = ref<{ configured: boolean; model: string | null } | null>(null)
const statusError = ref(''), useModel = ref(false), log = ref<HTMLElement | null>(null), input = ref<HTMLTextAreaElement | null>(null)
const panel = ref<HTMLElement | null>(null), confirmClear = ref(false), questionsOpen = ref(false)
const settingsOpen = ref(false)
// A mobile sheet owns focus; desktop remains a non-modal scene companion.
const inertSiblings = new Map<HTMLElement, boolean>()
let previousFocus: HTMLElement | null = null
function syncModalBackground() {
  for (const [element, wasInert] of inertSiblings) element.inert = wasInert
  inertSiblings.clear()
  if (!props.open || !mobile.value || !panel.value) return
  for (const sibling of panel.value.parentElement?.children ?? []) {
    if (sibling instanceof HTMLElement && sibling !== panel.value) {
      inertSiblings.set(sibling, sibling.inert)
      sibling.inert = true
    }
  }
}
const mobile = ref(window.matchMedia('(max-width: 760px)').matches)
const lastQuestion = ref(''), configurationLoading = ref(false)
const lastReply = computed(() => [...messages.value].reverse().find(m => m.reply)?.reply)
const focusKey = (value?: AssistantFocusContext | null) => value ? `${value.kind}:${value.id ?? value.label}` : ''
const focusChanged = computed(() => Boolean(lastReply.value && focusKey(lastReply.value.context.selection) !== focusKey(props.focusContext)))
const contextChanged = computed(() => lastReply.value && (lastReply.value.context.historical !== (props.atSeconds !== null) || focusChanged.value || (props.atSeconds !== null ? lastReply.value.context.at_seconds !== props.atSeconds : props.liveSeconds - lastReply.value.context.at_seconds >= 15)))
const viewportStyle = ref<Record<string, string>>({})
const compact = ref(false)
const media = window.matchMedia('(max-width: 760px)')
function updateViewport() {
  mobile.value = media.matches
  const viewport = window.visualViewport
  compact.value = mobile.value && (viewport?.height ?? innerHeight) < 560
  const topbar = panel.value?.parentElement?.querySelector('.director-topbar')?.getBoundingClientRect().bottom ?? 0
  const top = props.atSeconds === null ? Math.max(8, topbar + 8) : 8
  viewportStyle.value = mobile.value && viewport ? { top: `${viewport.offsetTop + top}px`, height: `${Math.max(160, viewport.height - top - 8)}px`, bottom: 'auto' } : {}
}
const suggestions = computed(() => {
  const focus = props.focusContext
  const contextual = focus?.kind === 'resident' ? [`为什么${focus.label}还没有到集合点？`, `如何调整${focus.label}的疏散路线？`]
    : focus?.kind === 'road' ? [`${focus.label}会影响哪些人员和任务？`, `这条道路封锁后应该如何改道？`]
    : focus?.kind === 'robot' ? ['机器人为什么停在这里？', '机器人下一项任务是什么？']
    : focus?.kind === 'command' ? ['这条指令为什么没有及时完成？', '这条指令下一步应该怎么处理？']
    : focus?.kind === 'score' ? ['这一项为什么扣分？', '怎样从相关事件前重新训练？']
    : focus?.kind === 'replay' ? ['这个历史时刻发生了什么？', '从这里换一种决策会有什么区别？'] : []
  return [...contextual, '现在下一步应该做什么？', '谁还没有到集合点？', '机器人为什么没动？', '道路拥堵应该怎么处理？', '如何从关键决定前重做？'].slice(0, 5)
})
function refreshContext(): void { void send(focusChanged.value ? suggestions.value[0] : lastQuestion.value) }
let controller: AbortController | null = null, statusController: AbortController | null = null, generation = 0
function clock(value: number) { return `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}` }
async function loadStatus() {
  statusError.value = ''; configurationLoading.value = true; statusController?.abort(); const request = new AbortController(); statusController = request
  const timeout = window.setTimeout(() => request.abort(), 8000)
  try {
    const value = await api.get<NonNullable<typeof provider.value>>('/assistant/status', { signal: request.signal }); if (statusController === request) { provider.value = value; if (!value.configured) useModel.value = false }
  } catch (cause) { if (statusController === request) { provider.value = null; useModel.value = false; statusError.value = cause instanceof Error && cause.name !== 'AbortError' && !(cause instanceof TypeError) ? cause.message : '暂时无法读取模型配置，请重新检查或使用离线解读。' } }
  finally { window.clearTimeout(timeout); if (statusController === request) configurationLoading.value = false }
}
async function scrollLog() { await nextTick(); log.value?.scrollTo({ top: log.value.scrollHeight, behavior: 'instant' }) }
async function toggleHelp(kind: 'settings' | 'questions') {
  confirmClear.value = false
  if (kind === 'settings') { settingsOpen.value = !settingsOpen.value; questionsOpen.value = false }
  else { questionsOpen.value = !questionsOpen.value; settingsOpen.value = false }
  await nextTick()
  const target = log.value?.querySelector<HTMLElement>(kind === 'settings' ? '.scene-assistant__settings' : '.scene-assistant__questions')
  if (target) target.scrollIntoView({ block: 'start', behavior: 'instant' })
}
async function toggleClear() { confirmClear.value = !confirmClear.value; settingsOpen.value = false; await nextTick(); log.value?.querySelector('.scene-assistant__confirm')?.scrollIntoView({ block: 'nearest' }) }
async function revealReply() { await nextTick(); const node = log.value?.querySelector<HTMLElement>('.scene-assistant__message:last-of-type'); if (node && log.value) log.value.scrollTop += node.getBoundingClientRect().top - log.value.getBoundingClientRect().top - 12 }
function fragments(message: Message) { return message.content.split(/(\[S\d+\])/g).map(text => ({ text, source: message.reply?.sources.some(s => `[${s.id}]` === text) ? text.slice(1, -1) : null })) }
function revealSource(index: number, id: string) { const section = log.value?.querySelectorAll<HTMLElement>('.scene-assistant__message')[index]; const details = section?.querySelector('details'); if (details) details.open = true; const source = section?.querySelector<HTMLElement>(`[data-source="${id}"]`); source?.scrollIntoView({ block: 'nearest', behavior: 'instant' }); source?.focus({ preventScroll: true }) }
function trapFocus(event: KeyboardEvent) { if (!mobile.value || event.key !== 'Tab') return; const targets = [...(panel.value?.querySelectorAll<HTMLElement>('button:not(:disabled), textarea, input, summary, [tabindex="0"]') ?? [])].filter(e => e.getClientRects().length > 0); const first = targets[0], last = targets[targets.length - 1]; if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() } }
function cancel() { generation++; controller?.abort(); controller = null; pending.value = false }
function clear() { cancel(); messages.value = []; question.value = ''; error.value = ''; confirmClear.value = false; lastQuestion.value = ''; void nextTick(() => input.value?.focus()) }
async function send(text = question.value) {
  const content = text.trim(); if (!content || pending.value || configurationLoading.value || content.length > 2000) return
  const requestUsesModel = useModel.value && !!provider.value?.configured
  error.value = ''; pending.value = true; question.value = ''; lastQuestion.value = content; questionsOpen.value = false; settingsOpen.value = false; confirmClear.value = false; if (mobile.value) input.value?.blur()
  if (messages.value[messages.value.length - 1]?.role === 'user') messages.value.pop()
  const history = messages.value.slice(-12).map(m => ({ role: m.role, content: m.content.slice(0, 2000) }))
  messages.value.push({ role: 'user', content }); await scrollLog()
  const request = ++generation; const requestController = new AbortController(); controller = requestController
  const timeout = window.setTimeout(() => requestController.abort(), 100_000)
  try {
    const reply = await api.post<Reply>(`/drills/${props.drillId}/assistant/chat`, { message: content, history, at_seconds: props.atSeconds, use_model: requestUsesModel, selection_context: props.focusContext ?? null }, { signal: requestController.signal })
    if (request !== generation) return
    messages.value.push({ role: 'assistant', content: reply.answer, reply }); await revealReply()
  } catch (cause) {
    if (request === generation) { question.value = content; error.value = cause instanceof DOMException && cause.name === 'AbortError' ? '等待已超时，请重试或切换离线解读。' : cause instanceof TypeError ? '暂时无法连接助手服务，请检查后端后重试。' : cause instanceof Error ? cause.message : '发送失败，请重试。' }
  } finally { window.clearTimeout(timeout); if (request === generation) { pending.value = false; controller = null; if (!mobile.value && props.open) void nextTick(() => input.value?.focus({ preventScroll: true })) } }
}
function stop() { const last = messages.value[messages.value.length - 1]; cancel(); if (last?.role === 'user') question.value = last.content; error.value = '已停止等待。模型端可能仍在处理，稍后可重试。' }
function onKey(event: KeyboardEvent) { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); void send() } }
function actionLabel(action: AssistantAction) {
  if (props.atSeconds === null) return action.label
  if (action.kind === 'branch') return '定位历史分支入口（需确认）'
  if (['command', 'rollcall', 'missions'].includes(action.kind)) return '返回实时现场 · ' + action.label
  return action.label
}
function navigate(action: AssistantAction) {
  if (action.kind === 'plan') { activeView.value = 'plan'; return }
  // The destination owns focus; only an ordinary close restores the opener.
  previousFocus = null
  emit('navigate', action)
}
watch(() => props.open, open => {
  confirmClear.value = false
  if (open) { if(!messages.value.length && !props.focusContext && props.atSeconds===null)activeView.value='plan'; previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null; updateViewport(); void nextTick(() => { if(activeView.value==='chat')input.value?.focus({ preventScroll: true }) }); if (!pending.value) void loadStatus() }
  else void nextTick(() => { if (previousFocus?.isConnected && !previousFocus.closest('[inert]') && previousFocus.getClientRects().length) previousFocus.focus({ preventScroll: true }) })
  if (!open) { if (!keepPlanPreview) emit('planPreview', []); keepPlanPreview = false }
})
watch([() => props.open, mobile], syncModalBackground, { flush: 'post' })
watch(error, async value => { if (value && props.open) { await nextTick(); log.value?.querySelector('.scene-assistant__error')?.scrollIntoView({ block: 'nearest' }) } })
watch(() => props.atSeconds, () => { if (pending.value) stop() })
onMounted(() => { void loadStatus(); updateViewport(); syncModalBackground(); media.addEventListener('change', updateViewport); window.visualViewport?.addEventListener('resize', updateViewport); window.visualViewport?.addEventListener('scroll', updateViewport) })
onBeforeUnmount(() => { for (const [element, wasInert] of inertSiblings) element.inert = wasInert; inertSiblings.clear(); cancel(); statusController?.abort(); statusController = null; media.removeEventListener('change', updateViewport); window.visualViewport?.removeEventListener('resize', updateViewport); window.visualViewport?.removeEventListener('scroll', updateViewport) })
</script>

<template>
  <aside v-show="open" ref="panel" class="scene-assistant" :class="{ 'is-compact': compact }" :style="viewportStyle" :role="mobile ? 'dialog' : undefined" :aria-modal="mobile ? true : undefined" aria-label="场景 AI 助手" @keydown="trapFocus" @keydown.esc.stop="confirmClear ? confirmClear = false : emit('close')">
    <div class="scene-assistant__top"><header class="scene-assistant__header"><div class="scene-assistant__identity"><AppIcon name="brain" :size="25" /><div><h2>安巷指挥助手</h2><p>{{ atSeconds === null ? '实时现场' : '历史 ' + clock(atSeconds) }} · {{ activeView === 'plan' ? '目标计划' : useModel && provider?.configured ? '模型问答' : '离线解读' }}</p></div></div><div><button type="button" aria-label="模型设置" title="模型设置" :aria-expanded="settingsOpen" aria-controls="scene-assistant-settings" @click="showSettings"><AppIcon name="settings" :size="18" /></button><button type="button" :disabled="!messages.length" aria-label="清空本场对话" title="清空本场对话" @click="toggleClear"><AppIcon name="refresh" :size="18" /></button><button type="button" aria-label="关闭 AI 助手" @click="emit('close')"><AppIcon name="close" /></button></div></header><nav class="scene-assistant__views" aria-label="助手工作视图"><button type="button" :aria-pressed="activeView==='chat'" @click="activeView='chat';emit('planPreview',[])"><AppIcon name="brain" :size="18" />场景对话</button><button type="button" :aria-pressed="activeView==='plan'" @click="activeView='plan'"><AppIcon name="route" :size="18" />目标计划</button></nav></div>
    <div v-if="mobile && atSeconds===null && ['running','paused'].includes(drillStatus??'')" class="scene-assistant__run-controls">
      <span>{{clock(liveSeconds)}} · {{drillStatus==='paused'?'已暂停':'进行中'}}</span>
      <button type="button" :disabled="busy" @click="emit('stateAction',drillStatus==='paused'?'resume':'pause')">{{drillStatus==='paused'?'继续演练':'暂停演练'}}</button>
      <button type="button" :disabled="busy" @click="emit('stateAction','end')">结束评分</button>
    </div>
    <div v-show="activeView==='chat'" ref="log" class="scene-assistant__log" aria-label="场景上下文与对话">
    <div class="scene-assistant__context"><AppIcon name="compass" :size="17" /><div><strong>{{ drillName }}</strong><span>{{ atSeconds === null ? '每次提问读取本场最新快照' : '正在解读历史时刻 ' + clock(atSeconds) }}</span></div><span class="scene-assistant__mode">{{ useModel && provider?.configured ? '模型问答' : '离线解读' }}</span></div>
    <details v-if="focusContext" :key="focusKey(focusContext)" class="scene-assistant__focus"><summary><AppIcon name="target" :size="17" /><span>当前关注<strong>{{ focusContext.label }}</strong></span><AppIcon name="chevron" :size="16" /></summary><p>{{ focusContext.detail || focusContext.type || '本轮提问将结合此对象的现场状态。' }}</p></details>
    <section class="scene-assistant__connection" aria-label="模型连接与授权">
      <div class="scene-assistant__connection-heading">
        <label v-if="provider?.configured" class="scene-assistant__consent"><input v-model="useModel" type="checkbox" :disabled="pending || configurationLoading" aria-describedby="scene-assistant-consent-note" />启用大模型问答</label>
        <span v-else>{{ configurationLoading ? '正在检查模型配置…' : statusError ? '模型配置读取失败' : '当前使用离线解读' }}</span>
        <button type="button" :aria-expanded="settingsOpen" aria-controls="scene-assistant-settings" @click="toggleHelp('settings')">模型设置<AppIcon name="chevron" :size="14" /></button>
      </div>
      <p v-if="provider?.configured" id="scene-assistant-consent-note">{{ useModel ? '已授权发送本场摘要、当前关注对象、问题与最近对话。' : '勾选后将本场摘要、当前关注对象、问题与最近对话发送给模型。' }}</p>
      <p v-if="statusError && !settingsOpen" class="scene-assistant__connection-hint">{{ statusError }}</p>
    </section>
    <div v-if="confirmClear" class="scene-assistant__confirm" role="group" aria-label="确认清空对话"><p>清空本场对话？此操作无法撤销，不影响演练数据。</p><div><button type="button" @click="confirmClear = false">保留对话</button><button type="button" @click="clear">确认清空</button></div></div>
    <div v-if="contextChanged" class="scene-assistant__stale"><span>{{ focusChanged ? '当前关注对象已切换，旧回答仍保留供对照。' : '现场或回放时刻已变化，旧回答不会自动更新。' }}</span><button type="button" :disabled="pending" @click="refreshContext">{{ focusChanged ? '解读当前对象' : '按新快照重答' }}</button></div>
      <section v-if="settingsOpen" id="scene-assistant-settings" class="scene-assistant__settings" aria-label="模型设置详情">
        <h3>模型设置</h3>
        <p>{{ provider?.configured ? '当前模型：' + provider.model : '管理员需在根目录 .env 配置模型地址、模型名称与密钥，然后重启后端。' }}</p>
        <p>授权仅在本场页面内有效，刷新或切换场次需重新勾选。未授权时使用离线规则解读；已配置不代表本次调用一定成功，请以回答标注的模式为准。</p>
        <p v-if="statusError" role="alert">{{ statusError }}</p>
        <button type="button" :disabled="pending || configurationLoading" @click="loadStatus">重新检查配置</button>
      </section>
      <section v-if="!messages.length" class="scene-assistant__welcome"><AppIcon name="brain" :size="32" /><h3>看不懂现场？<br />从一个问题开始。</h3><p>我可以结合本场居民、道路和任务解释当前情况，带你找到对应的操作入口。</p><p class="scene-assistant__boundary">只读建议，不替你执行指令。回答标注数据时间；演练变化后请重新提问。</p></section>
      <section v-if="questionsOpen || !messages.length" id="scene-assistant-questions" class="scene-assistant__questions" aria-label="常见场景问题">
        <h3>可以这样问</h3>
        <div class="scene-assistant__suggestions"><button v-for="item in suggestions" :key="item" type="button" :disabled="pending || configurationLoading" @click="send(item)">{{ item }}<AppIcon name="arrowRight" :size="14" /></button></div>
      </section>
      <div role="log" aria-label="场景对话记录" aria-live="polite" :aria-busy="pending">
      <article v-for="(message, index) in messages" :key="index" class="scene-assistant__message" :data-role="message.role">
        <div class="scene-assistant__speaker"><strong>{{ message.role === 'user' ? '你' : '安巷教练' }}</strong><span v-if="message.reply">{{ message.reply.mode === 'model' ? message.reply.model : '离线规则' }} · {{ clock(message.reply.context.at_seconds) }}{{ message.reply.context.historical ? ' 回放' : ' 快照' }}</span></div>
        <p class="scene-assistant__text"><template v-for="(fragment, part) in fragments(message)" :key="part"><button v-if="fragment.source" type="button" class="scene-assistant__citation" :aria-label="'查看依据 ' + fragment.source" @click="revealSource(index, fragment.source)">{{ fragment.text }}</button><template v-else>{{ fragment.text }}</template></template></p>
        <template v-if="message.reply"><p class="scene-assistant__notice">{{ message.reply.notice }}</p><details class="scene-assistant__sources"><summary>查看本轮数据依据 · {{ message.reply.sources.length }} 项</summary><dl><div v-for="source in message.reply.sources" :key="source.id" :data-source="source.id" tabindex="-1"><dt>[{{ source.id }}] {{ source.title }}</dt><dd>{{ source.detail }}</dd></div></dl></details><div v-if="message.reply.actions.length" class="scene-assistant__actions"><button v-for="action in message.reply.actions" :key="action.kind + (action.resident_id || '')" type="button" @click="navigate(action)">{{ actionLabel(action) }}<AppIcon name="arrowRight" :size="15" /></button></div></template>
      </article>
      <p v-if="pending" class="scene-assistant__pending" role="status">{{ useModel ? '正在请模型解读本场快照…' : '正在读取场景依据…' }}</p>
      </div>
      <div v-if="error" class="scene-assistant__error" role="alert"><p>{{ error }}</p><button type="button" :disabled="pending" @click="send(lastQuestion)">重试本次问题</button></div>
    </div>
    <div v-show="activeView==='plan'" class="scene-assistant__log" aria-label="目标计划工作区"><AgentPlanWorkspace :api-base-url="apiBaseUrl" :access-token="accessToken" :drill-id="drillId" :active="open&&activeView==='plan'" :historical="atSeconds!==null" :model-available="!!provider?.configured" :live-feed="agentFeed" :connection="connection" :focus-id="focusContext?.kind==='resident'?focusContext.id:undefined" @preview="previewPlan" @focus="id=>navigate({kind:'focus',label:'定位目标居民',resident_id:id})" @robot="navigate({kind:'focus',object_kind:'robot',label:'定位机器人'})" @indoor="id=>navigate({kind:'indoor',door_id:id,label:'检查受阻房门'})" @missions="navigate({kind:'missions',label:'查看案例责任任务'})" @rollcall="navigate({kind:'rollcall',label:'前往集合清点'})" @replay="at=>navigate({kind:'replay',label:'回看决策结果',at_seconds:at})" /></div>
    <div v-show="activeView==='chat'" class="scene-assistant__compose">
      <div class="scene-assistant__question-heading"><button type="button" :aria-expanded="questionsOpen || !messages.length" aria-controls="scene-assistant-questions" @click="toggleHelp('questions')">常见问题<AppIcon name="chevron" :size="14" /></button><span>{{ useModel && provider?.configured ? '本次发送给模型' : '本次为离线解读' }}</span></div>
      <form @submit.prevent="send()"><label class="sr-only" for="scene-assistant-question">向场景助手提问</label><textarea id="scene-assistant-question" ref="input" v-model="question" rows="2" maxlength="2000" placeholder="问问当前现场，例如：谁还没有到集合点？" :disabled="pending" aria-describedby="scene-assistant-input-hint" @keydown="onKey"></textarea><div class="scene-assistant__send"><span id="scene-assistant-input-hint">{{ question.length }}/2000 · Shift+Enter 换行</span><button v-if="pending" type="button" @click="stop">停止等待</button><button v-else type="submit" :disabled="!question.trim() || configurationLoading"><AppIcon name="send" :size="16" />{{ useModel && provider?.configured ? '发送给模型' : '离线解读' }}</button></div></form>
      <p class="scene-assistant__disclaimer">训练解读，不替代真实火场专业判断。对话仅在本场页面内保留。</p>
    </div>
  </aside>
</template>
