<script setup lang="ts">
import { createApiClient } from '../api/client'

import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { Community } from '../domain/models'
import AppIcon from './AppIcon.vue'
import TaskWorkflow from './TaskWorkflow.vue'
import type { ExerciseTask } from '../domain/task'

interface Scene { id: string; name: string; status: string }
type Task = ExerciseTask
interface EventItem { id: string; sequence: number; message: string; actor: string; event_type: string; elapsed_seconds: number }
interface Drill { id: string; name: string; status: string; elapsed_seconds: number; tasks: Task[]; events: EventItem[]; engine_version?: number; simulation: { residents?: Array<{ id: string; label: string; status: string; counted?: boolean; last_location?: string; search_responsible?: string }>; fire: { intensity: number }; summary: { total: number; evacuated: number; moving: number; missing: number; smoke_exposed?: number } } }

const props = defineProps<{ apiBaseUrl: string; accessToken?: string | null; community?: Community | null; drillId?: string; inviteCode?: string }>()
const api = createApiClient(props.apiBaseUrl, () => props.accessToken)
const emit = defineEmits<{ back: [] }>()
const drills = ref<Drill[]>([]), current = ref<Drill | null>(null), error = ref(''), busy = ref(false)
const role = ref(localStorage.getItem('zhiyan_participant_role') ?? '物业/网格员')
const connected = ref(false)
const invite = ref(props.inviteCode ?? '')
const displayName = ref(''), countedResidents = ref<string[]>([])
const member = ref<{ token: string; role: string; name: string } | null>(null)
const myTasks = computed(() => current.value?.tasks.filter(t => !t.responsible_role || t.responsible_role === role.value) ?? [])
const canAct = computed(() => !busy.value && current.value?.status === 'running' && ((current.value.engine_version ?? 1) < 2 || Boolean(member.value)))
let socket: WebSocket | null = null
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
    drills.value = await api.request<Drill[]>(`${props.apiBaseUrl}/scenes/${published.id}/drills`, { headers: headers() })
    if (drills.value[0]) selectDrill(drills.value.find((item) => ['running', 'paused', 'ready'].includes(item.status)) ?? drills.value[0])
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '参演端连接失败。' }
}
function selectDrill(drill: Drill): void {
  current.value = drill; socket?.close(); connected.value = false
  try { member.value = JSON.parse(localStorage.getItem('zhiyan_member_' + drill.id) ?? 'null'); if (member.value) role.value = member.value.role } catch { member.value = null }
  if (!invite.value && props.accessToken) void api.get<{code:string}>('/drills/' + drill.id + '/participant-invite').then(data => { if(!disposed) invite.value = data.code }).catch(cause=>{if(!disposed) error.value=cause instanceof Error?cause.message:'加入码读取失败，请重试。'})
  const credential = props.inviteCode ? `code=${encodeURIComponent(props.inviteCode)}` : `token=${encodeURIComponent(props.accessToken ?? '')}`
  socket = new WebSocket(api.websocketUrl(`/api/v1/ws/drills/${drill.id}?${credential}`))
  socket.onopen = () => { connected.value = true }
  socket.onmessage = (event) => { const message = JSON.parse(event.data) as { type: string; data: Drill }; if (message.type === 'drill.snapshot') current.value = message.data }
  socket.onclose = () => { connected.value = false; window.setTimeout(() => { if (!disposed && current.value?.id === drill.id) selectDrill(drill) }, 1800) }
}
function selectRole(value: string): void { if (member.value) return; role.value = value; localStorage.setItem('zhiyan_participant_role', value) }
async function join(): Promise<void> {
  if (!current.value || !invite.value) return
  busy.value = true; error.value = ''
  try {
    member.value = await api.request(props.apiBaseUrl + '/participant/drills/' + current.value.id + '/join?code=' + encodeURIComponent(invite.value), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ role: role.value, display_name: displayName.value.trim() }) })
    localStorage.setItem('zhiyan_member_' + current.value.id, JSON.stringify(member.value))
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '登记失败，请重试' } finally { busy.value = false }
}
function clearIdentity(): void { if (current.value) localStorage.removeItem('zhiyan_member_' + current.value.id); member.value = null; error.value = '' }
async function action(actionName: 'acknowledge' | 'arrived' | 'resource_ready' | 'resident_counted', message: string): Promise<void> {
  if (!current.value) return; busy.value = true; error.value = ''
  try { const path = invite.value ? `/participant/drills/${current.value.id}/actions?code=${encodeURIComponent(invite.value)}` : `/drills/${current.value.id}/participant-actions`; current.value = await api.request<Drill>(`${props.apiBaseUrl}${path}`, { method: 'POST', headers: { ...headers(), 'Content-Type': 'application/json' }, body: JSON.stringify({ role: role.value, action: actionName, message, resident_ids: countedResidents.value, participant_token: member.value?.token }) }) }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '反馈提交失败。' } finally { busy.value = false }
}
async function completeTask(taskId: string, taskAction: 'accept' | 'arrive' | 'submit', evidence: string): Promise<void> {
  if (!current.value) return; busy.value = true
  try { const path = `/participant/drills/${current.value.id}/tasks/${taskId}/actions?code=${encodeURIComponent(invite.value)}`; current.value = await api.request<Drill>(`${props.apiBaseUrl}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: taskAction, evidence, participant_token: member.value?.token }) }) }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '任务提交失败。' } finally { busy.value = false }
}
onMounted(() => void load())
onBeforeUnmount(() => { disposed = true; socket?.close() })
</script>

<template>
  <main id="main-content" class="participant-console">
    <header class="participant-header"><button type="button" @click="emit('back')"><AppIcon name="back" />退出参演</button><div><strong>{{ current?.name ?? '智演安巷' }}</strong></div><i :data-live="connected">{{ connected ? '实时' : '离线' }}</i></header>
    <section v-if="!current" class="participant-empty"><h1>正在加入演练</h1><p>{{ error || '正在读取现场与责任任务…' }}</p><button type="button" @click="load">重新连接</button></section>
    <template v-else>
      <section id="participant-scene" class="participant-hero" :data-alarm="current.status === 'running' && current.simulation.fire.intensity > 35"><div><span>{{ statusLabel }}</span><h1>{{ current.status === 'ended' ? '本轮演练已结束' : member ? '做好当前这一项处置' : '登记身份，接收责任任务' }}</h1><p>{{ current.status === 'ended' ? '下方保留你的任务结果，未完成项不再接受提交。' : latestAlert }}</p></div><strong>{{ clock }}</strong></section>
      <section id="participant-role" class="participant-role"><h2>我的参演身份</h2><p v-if="member">{{ member.name }} · {{ member.role }}</p><div v-else><button v-for="item in roles" :key="item" type="button" :aria-pressed="role === item" :data-active="role === item" @click="selectRole(item)">{{ item }}</button></div>
        <form v-if="(current.engine_version ?? 1) >= 2 && !member && current.status !== 'ended'" class="participant-join" @submit.prevent="join"><label for="participant-name">演练姓名或代号<input id="participant-name" v-model="displayName" minlength="2" maxlength="40" required autocomplete="nickname" placeholder="例如：物业一组" /></label><button type="submit" :disabled="busy || !invite || displayName.trim().length < 2">登记并接收任务</button><p>登记后身份绑定本场次，不随按钮切换。无需填写真实敏感身份信息。</p></form>
      </section>
      <p v-if="error" class="participant-error" role="alert">{{ error }} <button v-if="member" type="button" @click="clearIdentity">重新登记身份</button></p>
      <section id="participant-tasks" class="participant-tasks"><header><h2>{{ current.status === 'ended' ? '本场责任任务结果' : '我的当前任务' }}</h2><span>{{ myTasks.filter(t => t.status === 'completed').length }}/{{ myTasks.length }} 已完成</span></header>
        <TaskWorkflow v-for="task in myTasks" :key="task.id" :task="task" :running="canAct" :readonly="(current.engine_version ?? 1) >= 2 && !member" :busy="busy" @action="(actionName, evidence) => completeTask(task.id, actionName, evidence)" />
        <p v-if="!myTasks.length">当前没有分配给该角色的处置任务。可在下方回执告警与核验居民。</p>
      </section>
      <section v-if="current.status !== 'ended'" class="participant-feedback"><h2>现场回执</h2><div class="participant-actions"><button type="button" :disabled="!canAct" @click="action('acknowledge', '已收到火情告警，开始履行本角色职责')"><AppIcon name="pulse" /><strong>确认警报</strong><span>记录本次响应时间</span></button><button v-if="role === '物业/网格员'" type="button" :disabled="!canAct" @click="action('resource_ready', '已核对灭火器材与引导物资，资源准备就绪')"><AppIcon name="tasks" /><strong>资源就绪</strong><span>回执后影响处置模型</span></button></div>
        <form v-if="role !== '应急指挥人员'" class="resident-rollcall" @submit.prevent="action('resident_counted', '已在集合点核验所选居民身份')"><label for="rollcall">选择本次已核验居民（可多选）<select id="rollcall" v-model="countedResidents" multiple size="4"><option v-for="person in current.simulation.residents" :disabled="(current.engine_version ?? 1) >= 3 && (person.status !== 'evacuated' || person.counted)" :key="person.id" :value="person.id">{{ person.label }} · {{ person.status === 'evacuated' ? person.counted ? '已核验' : '已到集合点' : person.status === 'missing' ? '失联待核验' : '尚未到达' }}</option></select></label><button type="submit" :disabled="!canAct || !countedResidents.length">提交 {{ countedResidents.length }} 人核验结果</button><p>只能核验已经到达集合点的居民。未到人员需由导演指派搜索员，实际会合后继续撤离；清点不会解除失联。</p></form>
      </section>
      <section id="participant-result" class="participant-situation" aria-label="本场结果"><div><span>已疏散</span><strong>{{ current.simulation.summary.evacuated }}/{{ current.simulation.summary.total }}</strong></div><div><span>失联</span><strong>{{ current.simulation.summary.missing }}</strong></div></section>
      <nav class="participant-bottom-nav" aria-label="参演端快捷导航"><a href="#participant-scene"><AppIcon name="compass" />现场</a><a href="#participant-tasks"><AppIcon name="tasks" />任务</a><a href="#participant-role"><AppIcon name="person" />身份</a><a href="#participant-result"><AppIcon name="award" />结果</a></nav>
    </template>
  </main>
</template>
