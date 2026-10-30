<script setup lang="ts">
import { createApiClient } from '../api/client'
import { connectLive, isNewerState } from '../api/live'

import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { Community } from '../domain/models'
import AppIcon from './AppIcon.vue'
import TaskWorkflow from './TaskWorkflow.vue'
import CommunityPlan from './CommunityPlan.vue'
import type { DrillIndex, Simulation } from '../domain/drill'
import '../atlas-participant.css'
import type { ExerciseTask } from '../domain/task'

interface Scene { id: string; name: string; status: string }
type Task = ExerciseTask
interface EventItem { id: string; sequence: number; message: string; actor: string; event_type: string; elapsed_seconds: number }
interface Drill { state_version?: string; id: string; name: string; status: string; elapsed_seconds: number; tasks: Task[]; events: EventItem[]; engine_version?: number; simulation: { residents?: Array<{ id: string; label: string; status: string; counted?: boolean; last_location?: string; search_responsible?: string }>; fire: { intensity: number }; summary: { total: number; evacuated: number; moving: number; missing: number; smoke_exposed?: number } } }

const props = defineProps<{ apiBaseUrl: string; accessToken?: string | null; community?: Community | null; drillId?: string; inviteCode?: string }>()
const api = createApiClient(props.apiBaseUrl, () => props.accessToken)
const emit = defineEmits<{ back: [] }>()
const drills = ref<Drill[]>([]), current = ref<Drill | null>(null), error = ref(''), busy = ref(false)
const role = ref(localStorage.getItem('zhiyan_participant_role') ?? '物业/网格员')
const connected = ref(false)
type ParticipantView = 'task' | 'feedback' | 'rollcall' | 'result'
const participantView = ref<ParticipantView>('task')
function showParticipantView(view: ParticipantView) {
  participantView.value = view
  window.scrollTo({ top: 0, behavior: 'instant' })
}
const selectedTaskId=ref(''), reportOpen=ref(false), reportText=ref(''), notice=ref('')
const taskMapOpen=ref(typeof window === 'undefined' || !window.matchMedia('(max-width: 520px)').matches)
const activeTask=computed(()=>myTasks.value.find(t=>t.id===selectedTaskId.value)??myTasks.value.find(t=>t.status!=='completed')??myTasks.value[0])
const planSimulation=computed(()=>current.value?.simulation as Simulation|undefined)
const taskStep=computed(()=>({waiting:0,pending:0,executing:1,verifying:2,completed:3}[activeTask.value?.status??'']??0))
const invite = ref(props.inviteCode ?? '')
const displayName = ref(''), countedResidents = ref<string[]>([])
const member = ref<{ token: string; role: string; name: string; participant_id: string } | null>(null)
const presence = ref<'offline' | 'syncing' | 'online'>('offline')
const myTasks = computed(() => current.value?.tasks.filter(t => (!t.responsible_role || t.responsible_role === role.value) && (!t.assignee_id || t.assignee_id === member.value?.participant_id)) ?? [])
const canAct = computed(() => !busy.value && current.value?.status === 'running' && ((current.value.engine_version ?? 1) < 2 || Boolean(member.value)))
const arrivedUncounted = computed(() => current.value?.simulation.residents?.filter(person => person.status === 'evacuated' && !person.counted) ?? [])
const nextAction = computed(() => {
  if (!member.value || current.value?.status !== 'running') return null
  if (activeTask.value && activeTask.value.status !== 'completed') return { view: 'task' as const, label: '继续责任任务', title: activeTask.value.title }
  if (role.value !== '应急指挥人员' && arrivedUncounted.value.length) return { view: 'rollcall' as const, label: '下一项', title: `清点 ${arrivedUncounted.value.length} 名已到居民` }
  return { view: 'feedback' as const, label: '下一项', title: '提交现场回执' }
})
let stopLive: (() => void) | undefined
let heartbeatTimer: number | null = null
function applyCurrent(value: Drill) { if (!disposed && value.id === current.value?.id && isNewerState(value, current.value)) current.value = value }
let disposed = false
const roles = ['应急指挥人员', '物业/网格员', '居民代表']
if (!roles.includes(role.value)) role.value = '物业/网格员'
const clock = computed(() => { const value = current.value?.elapsed_seconds ?? 0; return `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}` })
const statusLabel = computed(() => ({ running: '现场演练进行中', ended: '演练已结束 · 当前仅查看复盘', paused: '演练已暂停 · 等待导演继续', ready: '演练准备中 · 等待导演开始' }[current.value?.status ?? ''] ?? '正在连接演练'))
const latestAlert = computed(() => current.value?.events.find((item) => item.event_type.startsWith('inject.'))?.message ?? '当前无新增险情')
const headers = (): HeadersInit => props.accessToken ? ({ Authorization: `Bearer ${props.accessToken}` }) : ({})

async function load(): Promise<void> {
  try {
    if (props.drillId && props.inviteCode) {
      const drill = await api.request<Drill>(`${props.apiBaseUrl}/participant/drills/${props.drillId}?code=${encodeURIComponent(props.inviteCode)}`)
      drills.value = [drill]; selectDrill(drill); return
    }
    if (!props.community || !props.accessToken) throw new Error('参演链接缺少场次信息。')
    const scenes = await api.request<Scene[]>(`${props.apiBaseUrl}/communities/${props.community.id}/scenes`, { headers: headers() })
    const published = scenes.find((item) => item.status === 'published'); if (!published) throw new Error('尚无已发布演练场景。')
    const index = await api.get<DrillIndex[]>(`/scenes/${published.id}/drills?summary=true`)
    const selected = index.find(item=>['running','paused','ready'].includes(item.status))??index[0]
    if(selected){const drill=await api.get<Drill>('/drills/'+selected.id);drills.value=[drill];selectDrill(drill)}
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '参演端连接失败。' }
}
function selectDrill(drill: Drill): void {
  stopLive?.()
  current.value = drill; connected.value = false
  try { member.value = JSON.parse(localStorage.getItem('zhiyan_member_' + drill.id) ?? 'null'); if (member.value) role.value = member.value.role } catch { member.value = null }
  if (!invite.value && props.accessToken && drill.status !== 'ended') void api.post<{code:string}>('/drills/' + drill.id + '/participant-invite').then(data => { if(!disposed) { invite.value = data.code; startHeartbeat() } }).catch(cause=>{if(!disposed) error.value=cause instanceof Error?cause.message:'加入码读取失败，请重试。'})
  stopLive = connectLive<Drill>({ getUrl: async () => {
    const admission = props.inviteCode
      ? await api.post<{ticket:string}>(`/participant/drills/${drill.id}/socket-ticket`, {code: props.inviteCode}, {auth:false})
      : await api.post<{ticket:string}>(`/drills/${drill.id}/socket-ticket`)
    return api.websocketUrl(`/api/v1/ws/drills/${drill.id}?ticket=${encodeURIComponent(admission.ticket)}`)
  }, drillId: drill.id, onState: applyCurrent, onStatus: state => { connected.value = state === 'live' }, onError: message => { error.value = message } })
  startHeartbeat()
}
function selectRole(value: string): void { if (member.value) return; role.value = value; localStorage.setItem('zhiyan_participant_role', value) }
async function join(): Promise<void> {
  if (!current.value || !invite.value) return
  busy.value = true; error.value = ''
  try {
    member.value = await api.request(props.apiBaseUrl + '/participant/drills/' + current.value.id + '/join?code=' + encodeURIComponent(invite.value), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ role: role.value, display_name: displayName.value.trim() }) })
    localStorage.setItem('zhiyan_member_' + current.value.id, JSON.stringify(member.value))
    startHeartbeat()
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '登记失败，请重试' } finally { busy.value = false }
}
async function heartbeat(): Promise<void> {
  if (!current.value || !member.value || !invite.value || disposed) return
  presence.value = 'syncing'
  try {
    const live = await api.request<{ participant_id: string; role: string; name: string }>(`${props.apiBaseUrl}/participant/drills/${current.value.id}/heartbeat?code=${encodeURIComponent(invite.value)}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ participant_token: member.value.token }) })
    if (member.value.participant_id !== live.participant_id) {
      member.value = { ...member.value, participant_id: live.participant_id }
      localStorage.setItem('zhiyan_member_' + current.value.id, JSON.stringify(member.value))
    }
    presence.value = 'online'
  } catch { presence.value = 'offline' }
}
function startHeartbeat(): void {
  if (heartbeatTimer !== null) window.clearInterval(heartbeatTimer)
  heartbeatTimer = null
  if (!member.value || !invite.value) return
  void heartbeat()
  heartbeatTimer = window.setInterval(() => void heartbeat(), 10_000)
}
async function clearIdentity(): Promise<void> {
  const drill = current.value, identity = member.value
  if (drill && identity && invite.value) {
    try { await api.request(`${props.apiBaseUrl}/participant/drills/${drill.id}/leave?code=${encodeURIComponent(invite.value)}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ participant_token: identity.token }) }) } catch { /* Local reset still recovers an invalid identity. */ }
  }
  if (heartbeatTimer !== null) window.clearInterval(heartbeatTimer)
  heartbeatTimer = null; presence.value = 'offline'
  if (drill) localStorage.removeItem('zhiyan_member_' + drill.id)
  member.value = null; error.value = ''
}
async function action(actionName: 'acknowledge' | 'arrived' | 'resource_ready' | 'resident_counted' | 'report', message: string): Promise<void> {
  if (!current.value) return; busy.value = true; error.value = ''
  try { const path = invite.value ? `/participant/drills/${current.value.id}/actions?code=${encodeURIComponent(invite.value)}` : `/drills/${current.value.id}/participant-actions`; applyCurrent(await api.request<Drill>(`${props.apiBaseUrl}${path}`, { method: 'POST', headers: { ...headers(), 'Content-Type': 'application/json' }, body: JSON.stringify({ role: role.value, action: actionName, message, resident_ids: countedResidents.value, participant_token: member.value?.token }) })); notice.value='反馈已写入本场证据，导演台将同步更新'; if(actionName==='report'){reportOpen.value=false;reportText.value=''} }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '反馈提交失败。' } finally { busy.value = false }
}
async function completeTask(taskId: string, taskAction: 'accept' | 'arrive' | 'submit', evidence: string): Promise<void> {
  if (!current.value) return; busy.value = true; error.value='';notice.value=''
  try { const path = `/participant/drills/${current.value.id}/tasks/${taskId}/actions?code=${encodeURIComponent(invite.value)}`; applyCurrent(await api.request<Drill>(`${props.apiBaseUrl}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: taskAction, evidence, participant_token: member.value?.token }) })); notice.value = taskAction === 'submit' ? '处置已核验，现场与过程评分同步更新' : taskAction === 'accept' ? '已接收任务，请到目标位置后回执到位' : '到位回执已记录，请完成处置后提交证据' }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '任务提交失败。' } finally { busy.value = false }
}
function syncWhenVisible(): void { if (document.visibilityState === 'visible') void heartbeat() }
onMounted(() => { document.addEventListener('visibilitychange', syncWhenVisible); void load() })
onBeforeUnmount(() => { disposed = true; stopLive?.(); if (heartbeatTimer !== null) window.clearInterval(heartbeatTimer); document.removeEventListener('visibilitychange', syncWhenVisible) })
</script>

<template>
  <main id="main-content" class="participant-console atlas-participant" data-ui-theme="immersive" :data-view="participantView">
    <header class="participant-header"><button type="button" @click="emit('back')"><AppIcon name="back" />退出参演</button><div><strong>{{ current?.name ?? '智演安巷' }}</strong></div><i :data-live="connected && (!member || presence === 'online')">{{ !connected ? '现场断线' : member && presence !== 'online' ? '身份同步中' : '实时在线' }}</i></header>
    <section v-if="!current" class="participant-empty"><h1>正在加入演练</h1><p>{{ error || '正在读取现场与责任任务…' }}</p><button type="button" @click="load">重新连接</button></section>
    <template v-else>
      <section id="participant-scene" class="participant-hero" :data-alarm="current.status === 'running' && current.simulation.fire.intensity > 35"><div><span>{{ statusLabel }}</span><h1>{{ current.status === 'ended' ? '本轮演练已结束' : member ? '做好当前这一项处置' : '登记身份，接收责任任务' }}</h1><details v-if="member && current.status !== 'ended'" class="participant-alert"><summary>现场消息</summary><p>{{ latestAlert }}</p></details><p v-else>{{ current.status === 'ended' ? '下方保留你的任务结果，未完成项不再接受提交。' : latestAlert }}</p></div><strong>{{ clock }}</strong></section>
      <section id="participant-role" class="participant-role" :data-joined="Boolean(member)"><h2>我的参演身份</h2><p v-if="member">{{ member.name }} · {{ member.role }}</p><div v-else><button v-for="item in roles" :key="item" type="button" :aria-pressed="role === item" :data-active="role === item" @click="selectRole(item)">{{ item }}</button></div>
        <form v-if="(current.engine_version ?? 1) >= 2 && !member && current.status !== 'ended'" class="participant-join" @submit.prevent="join"><label for="participant-name">演练姓名或代号<input id="participant-name" v-model="displayName" minlength="2" maxlength="40" required autocomplete="nickname" placeholder="例如：物业一组" /></label><button type="submit" :disabled="busy || !invite || displayName.trim().length < 2">登记并接收任务</button><p>登记后身份绑定本场次，不随按钮切换。无需填写真实敏感身份信息。</p></form>
      </section>
      <p v-if="error" class="participant-error" role="alert">{{ error }} <button v-if="member" type="button" @click="clearIdentity">重新登记身份</button></p>
      <p v-if="notice" class="atlas-participant-notice" role="status">{{notice}}</p>
      <button v-if="nextAction && participantView !== nextAction.view" type="button" class="atlas-next-action" @click="showParticipantView(nextAction.view)"><span><small>{{nextAction.label}}</small><strong>{{nextAction.title}}</strong></span><AppIcon name="arrowRight" /></button>
      <nav v-if="member || current.status === 'ended'" class="participant-view-nav" aria-label="参演工作区"><button v-for="tab in ([{id:'task',label:'责任任务'},{id:'feedback',label:'现场回执'},{id:'rollcall',label:'集合清点'},{id:'result',label:'结果'}] as const)" :key="tab.id" type="button" :aria-pressed="participantView === tab.id" @click="showParticipantView(tab.id)">{{tab.label}}<b v-if="tab.id==='rollcall' && arrivedUncounted.length">{{arrivedUncounted.length}}</b></button></nav>
      <section v-show="participantView === 'task'" id="participant-tasks" class="participant-tasks"><header><h2>{{ current.status === 'ended' ? '本场责任任务结果' : '我的当前任务' }}</h2><span>{{ myTasks.filter(t => t.status === 'completed').length }}/{{ myTasks.length }} 已完成</span></header>
        <label v-if="myTasks.length>1" class="atlas-task-select">切换责任任务<select v-model="selectedTaskId"><option value="">优先处理未完成任务</option><option v-for="task in myTasks" :key="task.id" :value="task.id">{{task.title}} · {{task.status==='completed'?'已完成':'待处理'}}</option></select></label>
        <template v-if="activeTask"><div class="atlas-task-title"><h2>{{activeTask.title}}</h2><span v-if="activeTask.overdue">已超时 · 可补救</span><p>{{activeTask.target}}</p></div><TaskWorkflow :key="activeTask.id" :task="activeTask" :running="canAct" :readonly="(current.engine_version ?? 1) >= 2 && !member" :busy="busy" @action="(actionName, evidence) => completeTask(activeTask!.id, actionName, evidence)" /><details v-if="planSimulation" class="atlas-task-map-disclosure" :open="taskMapOpen" @toggle="taskMapOpen=($event.currentTarget as HTMLDetailsElement).open"><summary><span>任务位置</span><small>{{taskMapOpen?'收起地图':'展开地图'}}</small></summary><div class="atlas-task-map"><CommunityPlan :simulation="planSimulation" :target="activeTask.target_position??undefined"/><span>实时场景平面 · 目标位置，不是手机定位</span></div></details><ol class="atlas-task-steps" aria-label="处置流程"><li v-for="(step,index) in ['接收任务','前往目标','处置核验','完成任务']" :key="step" :data-active="taskStep===index" :data-done="taskStep>index"><b>{{index+1}}</b><span>{{step}}</span></li></ol>
        </template>
        <p v-if="!myTasks.length">{{current.tasks.length?'本场尚无分配给此身份的任务。请联系导演核对责任角色。':'本场未配置处置任务。请导演在场景准备的“任务策略”中配置、执行选项并新建场次，已冻结场次不会自动加入任务。'}} 仍可在下方提交告警回执与居民清点。</p>
      </section>
      <section v-if="member&&current.status!=='ended'" class="atlas-participant-report"><button :aria-expanded="reportOpen" @click="reportOpen=!reportOpen"><AppIcon name="alert"/>报告异常 <small>遇到危险、无法到达等</small></button><form v-if="reportOpen" @submit.prevent="action('report',reportText)"><label>具体位置与异常情况<textarea v-model="reportText" minlength="6" maxlength="240" required placeholder="请说明所在位置、遇到的阻碍及需要的支援"/></label><button :disabled="!canAct||reportText.trim().length<6">发送给导演</button></form></section>
      <section v-if="current.status !== 'ended'" v-show="participantView === 'feedback' || participantView === 'rollcall'" id="participant-feedback" class="participant-feedback"><h2>{{participantView === 'rollcall' ? '集合清点' : '现场回执'}}</h2><div v-show="participantView === 'feedback'" class="participant-actions"><button type="button" :disabled="!canAct" @click="action('acknowledge', '已收到火情告警，开始履行本角色职责')"><AppIcon name="pulse" /><strong>确认警报</strong><span>记录本次响应时间</span></button><button v-if="role === '物业/网格员'" type="button" :disabled="!canAct" @click="action('resource_ready', '已核对灭火器材与引导物资，资源准备就绪')"><AppIcon name="tasks" /><strong>资源就绪</strong><span>回执后影响处置模型</span></button></div>
        <form v-if="role !== '应急指挥人员'" id="participant-rollcall" class="resident-rollcall" @submit.prevent="action('resident_counted', '已在集合点核验所选居民身份')"><label for="rollcall">选择本次已核验居民（可多选）<select id="rollcall" v-model="countedResidents" multiple size="4"><option v-for="person in current.simulation.residents" :disabled="(current.engine_version ?? 1) >= 3 && (person.status !== 'evacuated' || person.counted)" :key="person.id" :value="person.id">{{ person.label }} · {{ person.status === 'evacuated' ? person.counted ? '已核验' : '已到集合点' : person.status === 'missing' ? '失联待核验' : '尚未到达' }}</option></select></label><button type="submit" :disabled="!canAct || !countedResidents.length">提交 {{ countedResidents.length }} 人核验结果</button><p>只能核验已经到达集合点的居民。未到人员需由导演指派搜索员，实际会合后继续撤离；清点不会解除失联。</p></form>
      </section>
      <section v-show="participantView === 'result'" id="participant-result" class="participant-situation" aria-label="本场结果"><div><span>已疏散</span><strong>{{ current.simulation.summary.evacuated }}/{{ current.simulation.summary.total }}</strong></div><div><span>失联</span><strong>{{ current.simulation.summary.missing }}</strong></div></section>
      <nav class="participant-bottom-nav" aria-label="参演端快捷导航"><button type="button" :aria-pressed="participantView==='task'" @click="showParticipantView('task')"><AppIcon name="tasks" />任务</button><button type="button" :aria-pressed="participantView==='feedback'" @click="showParticipantView('feedback')"><AppIcon name="pulse" />回执</button><button type="button" :aria-pressed="participantView==='rollcall'" @click="showParticipantView('rollcall')"><AppIcon name="users" />清点</button><button type="button" :aria-pressed="participantView==='result'" @click="showParticipantView('result')"><AppIcon name="award" />结果</button></nav>
    </template>
  </main>
</template>
