<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import TaskWorkflow from './TaskWorkflow.vue'
import type { ExerciseTask } from '../domain/task'
import AppIcon from './AppIcon.vue'
import '../training.css'

export interface TrainingPerson {
  id: string; label: string; vulnerable: boolean; status: string; x: number; y: number
  assisted?: boolean; floor?: number; current_floor?: number; indoor_stage?: string; behavior?: string
  exit?: 'north' | 'south'; route_reachable?: boolean; congestion?: number
}
interface TrainingState {
  engine_version?: number; status: string; elapsed_seconds: number; tasks: ExerciseTask[]
  participants: Array<{ role: string; members?: Array<{ id: string; name: string; online: boolean }> }>
  robot: { x: number; y: number; state: string; current_task?: string | null; task_queue?: Array<{ label: string; status: string; progress: number; ends_at_seconds?: number }> } | null
  events: Array<{ event_type: string; elapsed_seconds: number; message: string }>
  score?: { total_score: number; details?: Array<{ name: string; score: number; max_score?: number; evidence: string }> } | null
  score_preview?: { total_score: number; details?: Array<{ name: string; score: number; max_score?: number; evidence: string }> }
  simulation: { residents: TrainingPerson[]; summary: { total: number; evacuated: number; missing: number; smoke_exposed?: number }; road_network?: { edges: Array<{ id: string; name: string; status: string }> } }
}
const props = defineProps<{ drill: TrainingState; busy: boolean; replay: boolean }>()
const emit = defineEmits<{
  start: []; resume: []; finish: []; retry: []; live: []; tasks: []; compare: []; indoor: []
  dispatch: [task: ExerciseTask]; locate: [task: ExerciseTask]; broadcast: []; assist: [ids: string[]]
  assign: [taskId: string, participantId: string]
  evacuate: [ids: string[], exit: 'north' | 'south']; focus: [id: string]
  task: [id: string, action: 'accept' | 'arrive' | 'submit', evidence: string]
  block: [id: string]; reopen: [id: string]; seek: [time: number]
}>()
const selectedRoad = ref(''), selectedPerson = ref('')
const panel = ref<HTMLElement | null>(null)
const people = computed(() => props.drill.simulation.residents)
const indoors = computed(() => people.value.filter(p => p.indoor_stage && p.indoor_stage !== 'outdoor'))
const outside = computed(() => people.value.filter(p => (!p.indoor_stage || p.indoor_stage === 'outdoor') && p.status !== 'evacuated'))
const needingHelp = computed(() => people.value.filter(p => p.vulnerable && !p.assisted && p.status !== 'evacuated'))
const unnotified = computed(() => indoors.value.some(p => p.indoor_stage === 'room'))
const fireConfirmed = computed(() => props.drill.events.some(e => e.event_type === 'robot.alarm_confirmed'))
const power = computed(() => props.drill.tasks.find(t => t.kind === 'power_off' && t.status !== 'completed'))
const broadcastTask = computed(() => props.drill.tasks.find(t => t.kind === 'broadcast'))
const broadcastDone = computed(() => props.drill.events.some(e => e.event_type === 'robot.broadcast_completed'))
const atEntrance = computed(() => {
  const t = broadcastTask.value?.target_position, r = props.drill.robot
  return !!(t && r && Math.hypot(t.x-r.x,t.y-r.y) <= 3 && ['arrived','completed'].includes(r.state))
})
const travelling = computed(() => props.drill.robot?.task_queue?.some(t => ['executing','queued'].includes(t.status)) ?? false)
const activeRobotTask = computed(() => props.drill.robot?.task_queue?.find(t => t.status === 'executing'))
const robotProgress = computed(() => Math.round(Math.max(0, Math.min(1, activeRobotTask.value?.progress ?? 0)) * 100))
const robotRemaining = computed(() => Math.max(0, Math.ceil((activeRobotTask.value?.ends_at_seconds ?? props.drill.elapsed_seconds) - props.drill.elapsed_seconds)))
const canAct = computed(() => !props.busy && !props.replay && props.drill.status === 'running')
const floorNumbers = computed(() => Array.from({ length: Math.max(1, ...people.value.map(p => p.floor ?? 1)) }, (_, i) => i+1).reverse())
const currentPerson = computed(() => people.value.find(p => p.id === selectedPerson.value))
const remainingTask = computed(() => props.drill.tasks.find(t => t.status !== 'completed'))
const uncounted = computed(() => (props.drill.engine_version ?? 2) >= 3 ? people.value.filter(p => !(p as TrainingPerson & {counted?:boolean}).counted).length : 0)
const indoorMoving = computed(() => indoors.value.filter(p => ['corridor','stairs','exit_queue'].includes(p.indoor_stage ?? '')).length)
const indoorWaiting = computed(() => Math.max(0, indoors.value.length - indoorMoving.value))
const liveScore = computed(() => props.drill.score?.total_score ?? props.drill.score_preview?.total_score ?? 0)
const weakestScore = computed(() => [...(props.drill.score?.details ?? props.drill.score_preview?.details ?? [])].sort((a,b) => ((b.max_score ?? b.score)-b.score)-((a.max_score ?? a.score)-a.score))[0])
const lastDecision = computed(() => props.drill.events.find(e => ['resident.command','inject.channel_blocked','road.reopened','robot.broadcast_completed','task.completed'].includes(e.event_type)))
const consequence = computed(() => {
  if (lastDecision.value?.event_type === 'robot.broadcast_completed') return '广播已经生效。看楼层圆点从等待转为准备、下楼，再到室外；广播不会让所有人立即出现在出口。'
  if (lastDecision.value?.event_type === 'inject.channel_blocked') return `封锁已写入当前路网。现在有 ${people.value.filter(p => p.status !== 'evacuated' && !p.route_reachable).length} 人的路线不可达；仍可达的人沿新路线继续移动。`
  if (lastDecision.value?.event_type === 'road.reopened') return '路段已恢复通行，机器人和居民重新规划；他们从当前位置继续，不会瞬间到达。'
  if (lastDecision.value?.event_type === 'task.completed') return '核验证据已保存。断电任务会减缓后续火势增长，既有烟气暴露不会被清零。'
  return `指令已生效。当前楼内 ${indoors.value.length} 人，室外 ${outside.value.length} 人；下楼、会合和沿路行走都需要演练时间。`
})
const stage = computed(() => {
  if (props.replay) return { title: '这是当时的现场', why: '人员、道路和任务均已回到这个时刻。当前只读，不会修改正在进行的演练。', key: 'replay' }
  if (props.drill.status === 'ready') return { title: '把居民从楼内带到集合点', why: '你扮演社区指挥员：确认火情、安排断电、通知撤离、照顾重点人员。先完成一次，再比较另一种选择。', key: 'ready' }
  if (props.drill.status === 'paused') return { title: '演练已暂停', why: '仿真时钟停止，居民和机器人不会继续移动。可以观察现场，准备下一条指令。', key: 'paused' }
  if (props.drill.status === 'ended') return { title: '这次指挥带来了什么结果？', why: `共 ${people.value.length} 人，${props.drill.simulation.summary.evacuated} 人到达集合点，${props.drill.simulation.summary.missing} 人失联。查看关键决定，区分遗漏与已完成处置。`, key: 'ended' }
  if (!fireConfirmed.value) return { title: '机器人正在确认火情', why: '先观察巡检。机器人沿道路到达火点附近，连续采样三次后触发处置任务。居民此时仍在楼内等待通知。', key: 'perception' }
  if (power.value) return { title: '火情已确认：安排断电处置', why: '在下方接收任务、回执到位并记录结果。核验完成后，模型中的火势增速降低；这里是演练回执，不会控制真实电源。', key: 'power' }
  if (needingHelp.value.length) return { title: `${needingHelp.value.length} 名重点居民需要接应`, why: '先预览接应路线，再在下方确认下达。接应人员会沿楼门、楼梯与走廊实际会合，不会点击后瞬间完成。', key: 'assist' }
  if (!broadcastDone.value && broadcastTask.value) return { title: atEntrance.value ? '机器人已到入口：通知居民撤离' : '居民还没有收到疏散通知', why: travelling.value && !atEntrance.value ? '机器人正在路上。到达入口后，下面会出现广播按钮；不要重复派出同一目标。' : '派机器人到住宅入口并执行广播，居民才会离开房间、排队下楼。你也可以在下方直接指定一组居民撤离。', key: 'broadcast' }
  if (outside.value.some(p => !p.route_reachable)) return { title: '有人被阻断在室外', why: '展开道路操作解除封锁，或给所选居民改派另一出口。不能到达集合点时，系统不会宣布疏散完成。', key: 'observe' }
  if (props.drill.simulation.summary.evacuated === people.value.length) return { title: '人员已到集合点，核对清点与处置', why: uncounted.value ? `还有 ${uncounted.value} 人未核验。打开下方「清点」，逐人确认到场；到出口不等于完成清点。` : remainingTask.value ? '人员清点已完成，请补齐下方任务证据。' : '本场人员清点与任务已完成，可以结束复盘，或从一次决定前重新选择。', key: 'complete' }
  return { title: indoors.value.length ? '观察居民下楼与楼门排队' : '观察两条出口路线', why: `${indoors.value.length} 人还在楼内，${outside.value.length} 人在室外。楼梯有通行容量，重点人员速度较慢；不要把尚未到达误认为系统没有运行。`, key: 'observe' }
})
const workflow = computed(() => stage.value.key === 'power' ? power.value : stage.value.key === 'complete' ? remainingTask.value : undefined)
const workflowAssignees = computed(() => props.drill.participants.find(item => item.role === workflow.value?.responsible_role)?.members?.filter(item => item.online) ?? [])
const nextScoreHint = computed(() => ({
  ready: '开始后，系统按实际处置结果记分',
  perception: '完成连续采样并确认火情，可获得感知证据',
  power: '接收、到位、提交证据，才计入任务得分',
  assist: '与重点居民实际会合并护送，才计入护送得分',
  broadcast: '机器人到达入口并完成广播，居民才开始撤离',
  observe: '居民到达集合点并完成清点，疏散分才会增长',
  complete: '补齐清点和任务证据后再结束演练',
  ended: '本场分数已冻结，可从证据定位失分原因',
  paused: '仿真已暂停，继续后人员和车辆才会移动',
  replay: '历史回看不改变本场分数',
}[stage.value.key] ?? '操作产生现场结果与证据后才计分'))
watch(() => stage.value.key, () => { if (!panel.value?.contains(document.activeElement)) panel.value?.scrollTo({ top: 0, behavior: 'instant' }) }, { flush: 'post' })
function floorPeople(floor: number) { return indoors.value.filter(p => Math.max(1, Math.ceil(p.current_floor ?? p.floor ?? 1)) === floor) }
function choosePerson(id: string) { selectedPerson.value = id; emit('focus', id) }
function split() {
  const candidates = people.value.filter(p => !p.vulnerable && p.status !== 'evacuated')
  emit('evacuate', candidates.map(p => p.id), 'north')
}
</script>

<template>
  <aside ref="panel" class="training-panel" aria-label="引导演练">
    <header><h1>社区消防引导演练</h1><p>你是指挥员。做一个决定，观察现场变化。</p></header>
    <section class="training-next" aria-label="现在该做什么">
      <h2 aria-live="polite">{{ stage.title }}</h2><p>{{ stage.why }}</p>
      <button v-if="stage.key === 'ready'" :disabled="busy" @click="emit('start')"><AppIcon name="play" />开始引导演练</button>
      <button v-else-if="stage.key === 'paused'" :disabled="busy" @click="emit('resume')">继续本次训练</button>
      <button v-else-if="stage.key === 'replay'" @click="emit('live')">返回本场最新状态</button>
      <button v-else-if="stage.key === 'assist'" :disabled="!canAct" @click="emit('assist', needingHelp.map(p => p.id))">预览并安排 {{ needingHelp.length }} 名重点居民接应</button>
      <template v-else-if="stage.key === 'broadcast'">
        <button v-if="atEntrance" :disabled="!canAct" @click="emit('broadcast')">广播：通知楼内居民撤离</button>
        <button v-else :disabled="!canAct || travelling" @click="broadcastTask && emit('dispatch', broadcastTask)">{{ travelling ? '机器人移动中，等待到达入口' : '派机器人到住宅入口' }}</button>
      </template>
      <p v-if="stage.key === 'perception'" role="status">已记录 {{ drill.events.filter(e => e.event_type === 'robot.sensor_sample').length }}/3 次近场采样。<button class="training-link" @click="emit('tasks')">查看机器人路线与任务</button></p>
      <TaskWorkflow v-if="workflow" :key="workflow.id" :task="workflow" :running="drill.status === 'running' && !replay" :busy="busy" :assignees="workflowAssignees" director @assign="participantId => emit('assign', workflow!.id, participantId)" @action="(action, evidence) => emit('task', workflow!.id, action, evidence)" @locate="emit('locate', workflow)" @dispatch="emit('dispatch', workflow)" />
      <button v-if="stage.key === 'complete'" :disabled="!canAct || uncounted > 0 || Boolean(remainingTask)" @click="emit('finish')">结束训练并查看结果</button>
      <template v-if="stage.key === 'ended'"><button @click="emit('tasks')">检查任务与遗漏</button><button @click="emit('compare')">比较另一种出口选择</button><button :disabled="busy" @click="emit('retry')">重新训练一次</button></template>
      <ul v-if="stage.key === 'ended'" class="training-omissions"><li v-for="t in drill.tasks.filter(t => t.status !== 'completed')" :key="t.id">未核验：{{ t.title }}</li><li v-if="people.some(p => p.status !== 'evacuated')">仍有 {{ people.filter(p => p.status !== 'evacuated').length }} 人未到出口；回看下楼、封路和疏散通知的时刻。</li><li v-if="!broadcastDone">本场没有广播证据，请检查是否只派出机器人却忘记通知居民。</li></ul>
      <div v-if="drill.status !== 'ready'" class="training-live-state" aria-live="polite">
        <div class="training-live-state__command"><span>当前执行</span><strong v-if="activeRobotTask">{{ activeRobotTask.label }} · {{ robotProgress }}%</strong><strong v-else>{{ busy ? '正在写入指令…' : (drill.status === 'paused' ? '已暂停' : '现场持续推演中') }}</strong><small v-if="activeRobotTask">约 {{ robotRemaining }} 秒后到达；到达前不能执行目标点任务</small><small v-else>人员与车辆按演练时钟连续移动</small></div>
        <div class="training-flow-live" aria-label="人员实时疏散进度"><span><b>{{ indoorWaiting }}</b> 楼内等待</span><span><b>{{ indoorMoving }}</b> 下楼排队</span><span><b>{{ outside.length }}</b> 室外移动</span><span><b>{{ drill.simulation.summary.evacuated }}</b> 到集合点</span></div>
        <div class="training-score-line"><span>过程分 <strong>{{ liveScore }}/100</strong></span><small>{{ nextScoreHint }}。过程分会随烟气暴露和处置结果实时升降。</small></div>
        <p v-if="weakestScore" class="training-score-gap">当前主要失分：{{ weakestScore.name }} {{ weakestScore.score }}/{{ weakestScore.max_score ?? '—' }} · {{ weakestScore.evidence }}</p>
      </div>
    </section>
    <slot />
    <section v-if="(drill.engine_version ?? 2) < 3 && (indoors.length || people.some(p => p.floor))" class="training-building" aria-label="楼内疏散剖面">
      <h2>从楼内到出口</h2><p>示意楼层 · 非真实户型。点击人员圆点查看状态。</p>
      <button @click="emit('indoor')">查看三维楼内示意剖面</button>
      <div class="training-flow"><span>楼内 {{ indoors.length }}</span><span>室外 {{ outside.length }}</span><span>到出口 {{ drill.simulation.summary.evacuated }}</span></div>
      <div v-for="floor in floorNumbers" :key="floor" class="training-floor">
        <strong>{{ floor }}F</strong><div><button v-for="person in floorPeople(floor)" :key="person.id" :data-stage="person.indoor_stage" :data-vulnerable="person.vulnerable" :aria-label="person.label + '，' + person.behavior" :title="person.label + '：' + person.behavior" @click="choosePerson(person.id)"><span></span></button></div><small>{{ floorPeople(floor).length }} 人</small>
      </div>
      <p class="training-key">浅绿：等待通知　金色：重点人员　蓝色：正在下楼</p>
      <p v-if="unnotified">楼内等待不是故障：需要广播或直接下达居民疏散指令。</p>
    </section>
    <section v-if="(drill.engine_version ?? 2) < 3" class="training-people">
      <h2>指挥居民</h2>
      <label>选择要查看或指挥的人<select aria-label="选择要查看或指挥的人" v-model="selectedPerson" @change="choosePerson(selectedPerson)"><option value="">请选择居民</option><option v-for="p in people" :key="p.id" :value="p.id">{{ p.label }}{{ p.vulnerable ? '（重点）' : '' }} · {{ p.behavior }}</option></select></label>
      <p v-if="currentPerson" role="status">{{ currentPerson.label }}：{{ currentPerson.behavior }}。{{ currentPerson.indoor_stage && currentPerson.indoor_stage !== 'outdoor' ? '请在楼层剖面查看，尚未出现在室外。' : '三维镜头已定位此人。' }}</p>
      <div class="training-actions"><button :disabled="!canAct || !currentPerson || currentPerson.status === 'evacuated'" @click="emit('evacuate', [selectedPerson], 'north')">此人向北门</button><button :disabled="!canAct || !currentPerson || currentPerson.status === 'evacuated'" @click="emit('evacuate', [selectedPerson], 'south')">此人向南门</button></div>
      <button :disabled="!canAct || !people.some(p => !p.vulnerable && p.status !== 'evacuated')" @click="split">普通居民向北门撤离</button>
      <button :disabled="!canAct || !people.some(p => !p.vulnerable && p.status !== 'evacuated')" @click="emit('evacuate', people.filter(p => !p.vulnerable && p.status !== 'evacuated').map(p => p.id), 'south')">普通居民向南门撤离</button>
    </section>
    <details class="training-roads"><summary>试试封路与改道</summary><p>这是导演制造的训练扰动，不是现实中的处置建议。封锁后观察路线，再解除封锁。</p><label>选择道路<select v-model="selectedRoad" aria-label="选择道路"><option value="">请选择路段</option><option v-for="road in drill.simulation.road_network?.edges" :key="road.id" :value="road.id">{{ road.name }} · {{ road.status === 'blocked' ? '已封锁' : '可通行' }}</option></select></label><button :disabled="!canAct || !selectedRoad" @click="drill.simulation.road_network?.edges.find(e => e.id === selectedRoad)?.status === 'blocked' ? emit('reopen', selectedRoad) : emit('block', selectedRoad)">{{ drill.simulation.road_network?.edges.find(e => e.id === selectedRoad)?.status === 'blocked' ? '解除此路封锁' : '制造此路封锁' }}</button></details>
    <section v-if="lastDecision && (drill.engine_version ?? 2) < 3" class="training-feedback"><h2>刚才的决定</h2><p>{{ lastDecision.message }}</p><p>{{ consequence }}</p><button @click="emit('seek', Math.max(0, lastDecision.elapsed_seconds - 1))">回看决定之前</button><button @click="emit('compare')">比较其他出口方案</button><small>比较结果来自规则预测，不代表真实火场结果。</small></section>
  </aside>
</template>
