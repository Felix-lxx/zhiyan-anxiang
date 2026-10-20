<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { createApiClient } from '../api/client'
import { canApplyAgentRun, type AgentAssignment, type AgentCandidate, type AgentRun, type AgentLiveState } from '../domain/agent'
import AppIcon from './AppIcon.vue'
import AgentOutcomeReview from './AgentOutcomeReview.vue'

const props = defineProps<{ apiBaseUrl:string;accessToken:string;drillId:string;active:boolean;historical:boolean;modelAvailable:boolean;focusId?:string;liveFeed?:AgentLiveState|null;connection?:'connecting'|'live'|'stale' }>()
const emit = defineEmits<{ preview:[people:AgentAssignment[]];focus:[id:string];robot:[];rollcall:[];replay:[at:number] }>()
const api = createApiClient(props.apiBaseUrl, () => props.accessToken)
const goal = ref('将目标居民分流疏散，重点人员安排护送'), building = ref(''), assist = ref(true), useModel = ref(false)
const robotBroadcast = ref(false)
const expandedStep = ref('')
const buildings = ref<Array<{id:string;name:string}>>([]), runs = ref<AgentRun[]>([]), drillStatus = ref('')
const loading = ref(false), busy = ref(false), error = ref(''), syncError = ref(''), chosen = ref(''), detail = ref<'plan'|'execution'|'evidence'>('plan')
let timer:ReturnType<typeof setTimeout>|undefined, generation=0, pollEpoch=0, requestId='', disposed=false
let readController:AbortController|null=null
const run = computed(() => runs.value[0])
const streamReady=computed(()=>props.connection==='live' && props.liveFeed?.id===props.drillId)
const coordination = computed(() => run.value?.execution?.coordination)
const laneLabels:Record<string,string> = { observing:'持续核对',paused:'现场冻结',review:'需要复核',approval:'待人工确认',confirmed:'已确认',waiting:'等待条件',attention:'需要关注' }
const candidate = computed(() => run.value?.candidates.find(p => p.id===chosen.value) ?? run.value?.candidates[0])
const live = computed(() => !props.historical && drillStatus.value==='running')
const canCreate = computed(() => !run.value || ['completed','stopped','taken_over','unfinished'].includes(run.value.status))
const labels:Record<string,string> = { awaiting_approval:'待确认方案',executing:'执行中',waiting:'等待条件',needs_review:'现场变化，待调整',paused:'演练已暂停',awaiting_rollcall:'到场，待人工清点',completed:'目标完成',stopped:'已停止自动下令',taken_over:'已让出控制',unfinished:'本场已结束',pending:'等待条件',accepted:'已受理',queued:'排队',blocked:'受阻',superseded:'已被替代',cancelled:'已取消',failed:'执行失败' }
const stepSummary = computed(() => {
  const steps = run.value?.steps ?? []
  return { total:steps.length, completed:steps.filter(step => step.status === 'completed').length }
})
function dependencyLabel(step: { depends_on?:string[] }) {
  return step.depends_on?.map(id => run.value?.steps.find(item => item.id === id)?.label).filter(Boolean).join('、')
}
const clock = (seconds:number) => `${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(Math.floor(seconds%60)).padStart(2,'0')}`
const signed = (value:number) => `${value>0?'+':''}${value}`
function nextAction() {
  const action=coordination.value?.next_action
  if (!action || busy.value || syncError.value) return
  if (action.kind==='replan') void act('replan')
  else if (action.kind==='rollcall') emit('rollcall')
  else if (action.kind==='robot') emit('robot')
  else if (action.kind==='focus' && action.resident_id) emit('focus', action.resident_id)
  else detail.value=action.kind==='review'?'plan':run.value?.status==='completed'?'evidence':'execution'
}
function setRun(value:AgentRun) {
  const changed = run.value?.id !== value.id
  runs.value = [value,...runs.value.filter(r => r.id!==value.id)]
  if (!value.candidates.some(p => p.id===chosen.value)) chosen.value=value.candidates[0]?.id ?? ''
  if (changed) detail.value=value.steps.length?'execution':'plan'
  if (!value.steps.some(step => step.id===expandedStep.value)) expandedStep.value=(value.steps.find(step=>['blocked','waiting','executing'].includes(step.status))??value.steps[0])?.id??''
}
function applyStream() {
  if(!streamReady.value || !props.liveFeed || !props.active || props.historical || busy.value || disposed)return
  const value=props.liveFeed, incoming=value.runs[0]
  if(incoming && !canApplyAgentRun(incoming,run.value))return
  // An in-flight pre-creation frame cannot erase an HTTP-confirmed new plan.
  if(!incoming && run.value)return
  generation++;readController?.abort();loading.value=false;syncError.value=''
  buildings.value=value.buildings;drillStatus.value=value.drill_status
  if(incoming)setRun(incoming)
  runs.value=value.runs
}
async function read(initial=false, reconcile=false) {
  if (!props.active || props.historical || disposed || (busy.value && !reconcile)) return
  if(streamReady.value&&!reconcile){applyStream();return}
  const version=generation, scope=props.drillId
  readController?.abort(); const controller=new AbortController();readController=controller
  if (initial) loading.value=true
  try {
    const value=await api.get<{buildings:Array<{id:string;name:string}>;runs:AgentRun[];drill_status:string}>(`/drills/${scope}/agent/runs`,{signal:AbortSignal.any([controller.signal,AbortSignal.timeout(10000)])})
    if (version!==generation || scope!==props.drillId || disposed) return
    buildings.value=value.buildings;drillStatus.value=value.drill_status;syncError.value=''
    if(value.runs[0])setRun(value.runs[0])
    runs.value=value.runs
    if (run.value?.candidates.length && !run.value.candidates.some(p=>p.id===chosen.value)) chosen.value=run.value.candidates[0]!.id
  } catch(cause) { if (version===generation && !controller.signal.aborted) syncError.value=cause instanceof Error?cause.message:'目标计划读取失败，请重试。' }
  finally { if(version===generation)loading.value=false;if(readController===controller)readController=null }
}
async function poll(epoch=pollEpoch) {
  if(!streamReady.value)await read()
  if(epoch===pollEpoch && props.active && !props.historical && !disposed) timer=setTimeout(()=>poll(epoch),3000)
}
async function create() {
  if(busy.value || props.historical || !goal.value.trim())return
  busy.value=true;error.value='';generation++;readController?.abort();const version=generation,scope=props.drillId
  requestId ||= globalThis.crypto?.randomUUID?.() ?? `goal-${Date.now()}-${Math.random().toString(36).slice(2)}`
  try {
    const value=await api.post<AgentRun>(`/drills/${scope}/agent/runs`,{request_id:requestId,goal:goal.value,building_id:building.value||null,resident_ids:!building.value&&props.focusId?.startsWith('resident-')?[props.focusId]:[],priority_assist:assist.value,robot_broadcast:robotBroadcast.value,use_model:useModel.value&&props.modelAvailable},{signal:AbortSignal.timeout(60000)})
    if(version!==generation||disposed)return
    setRun(value);detail.value='plan';requestId=''
  } catch(cause){if(version===generation)error.value=cause instanceof Error?cause.message:'方案生成失败，请重试。'}
  finally{if(version===generation)busy.value=false}
}
async function act(action:'approve'|'stop'|'replan'|'review') {
  if(!run.value||busy.value||props.historical)return
  generation++;readController?.abort();const current=run.value,version=generation;busy.value=true;error.value=''
  try{
    const value=await api.post<AgentRun>(`/drills/${props.drillId}/agent/runs/${current.id}/actions`,{action,revision:current.revision,candidate_id:action==='approve'?candidate.value?.id:null},{signal:AbortSignal.timeout(30000)})
    if(version!==generation||disposed)return
    setRun(value);detail.value=action==='approve'?'execution':'plan';emit('preview',[])
  }catch(cause){if(version===generation){error.value=cause instanceof Error?cause.message:'计划操作失败';await read(false,true)}}
  finally{if(version===generation)busy.value=false}
}
function showRoute(value:AgentCandidate){
  chosen.value=value.id
  // Show a bounded sample per exit; every resident still participates in the plan.
  const sample=(['north','south'] as const).flatMap(exit=>{
    const members=value.assignments.filter(p=>p.exit===exit), stride=Math.max(1,Math.ceil(members.length/24))
    return members.filter((_,index)=>index%stride===0).slice(0,24)
  })
  const robot = value.robot_support
  if (robot?.route_points.length) {
    sample.push({ id:'agent-robot-route', label:robot.target, exit:'north', vulnerable:false,
      route_kind:'robot', route_reachable:robot.can_apply, route_points:robot.route_points })
  }
  emit('preview',sample)
}
watch([goal,building,assist,useModel,robotBroadcast,()=>props.focusId],()=>{requestId=''})
watch([()=>props.liveFeed,streamReady,()=>props.active,()=>props.historical,busy],applyStream,{flush:'post'})
watch(chosen,()=>emit('preview',[]),{flush:'sync'})
watch(()=>props.drillId,()=>{runs.value=[];buildings.value=[];chosen.value='';expandedStep.value='';building.value='';requestId='';error.value='';syncError.value='';drillStatus.value=''})
watch([()=>props.active,()=>props.historical,()=>props.drillId],()=>{
  generation++;pollEpoch++;busy.value=false;loading.value=false;readController?.abort();clearTimeout(timer)
  if(props.historical)emit('preview',[])
  if(props.active&&!props.historical){const epoch=pollEpoch;void read(true).then(()=>{if(epoch===pollEpoch&&!disposed)timer=setTimeout(()=>poll(epoch),3000)})}
},{immediate:true})
onBeforeUnmount(()=>{disposed=true;generation++;pollEpoch++;clearTimeout(timer);readController?.abort();emit('preview',[])})
</script>

<template>
  <section class="agent-workspace" aria-label="疏散目标计划" :aria-busy="busy||loading">
    <p v-if="historical" class="agent-workspace__notice">正在查看历史现场。返回实时现场后可制定或执行目标计划，历史解读仍在对话中查看。</p>
    <template v-else>
      <div class="agent-workspace__intro"><h3>疏散协同智能体</h3><p>设定目标，比较出口方案，确认后持续监督居民、护送员与机器人。现场变化时提示复核，到场后转交人工清点。</p></div>
      <p v-if="connection" class="agent-workspace__sync" role="status"><AppIcon :name="streamReady?'pulse':'refresh'" :size="17" />{{streamReady?'与三维现场实时联动':connection==='stale'?'连接恢复中，定时核对最近状态':'正在连接现场，暂用状态读取'}}</p>
      <p v-if="syncError" class="agent-workspace__error" role="alert">{{syncError}} <button type="button" @click="read(true)">重新连接</button></p>
      <p v-if="loading&&!run" role="status">正在恢复本场目标计划…</p>
      <form v-if="canCreate&&!loading" class="agent-workspace__form" @submit.prevent="create">
        <label>演练目标<textarea v-model="goal" rows="3" maxlength="2000" :disabled="busy" placeholder="例如：将三号楼居民分流疏散，并护送重点人员" /></label>
        <label>目标范围<select v-model="building" :disabled="busy"><option value="">{{focusId?.startsWith('resident-')?'当前选中居民':'全部待撤离居民（或按目标解析建筑）'}}</option><option v-for="item in buildings" :key="item.id" :value="item.id">{{item.name}}</option></select></label>
        <label class="agent-workspace__check"><input type="checkbox" v-model="assist" :disabled="busy" />重点人员安排护送</label>
        <div class="agent-workspace__resource-option">
          <label class="agent-workspace__check"><input type="checkbox" v-model="robotBroadcast" :disabled="busy" />机器人到楼门广播</label>
          <p class="agent-workspace__meta">需明确一栋建筑；与居民撤离并行，不会覆盖已有机器人任务。</p>
        </div>
        <label v-if="modelAvailable" class="agent-workspace__check"><input type="checkbox" v-model="useModel" :disabled="busy" />授权模型解析目标与建筑清单</label>
        <p class="agent-workspace__meta">{{useModel&&modelAvailable?'模型解析目标，本地校验和仿真规划。':'本地目标解析与仿真规划，不调用大模型。'}} 生成方案不会下达指令。</p>
        <button type="submit" class="agent-workspace__primary" :disabled="busy||!goal.trim()||drillStatus==='ended'"><AppIcon name="route" :size="18" />{{busy?'正在比较方案…':'生成并比较方案'}}</button>
      </form>
      <p v-if="error" class="agent-workspace__error" role="alert">{{error}}</p>
      <article v-if="run" class="agent-workspace__run">
        <header><strong>{{labels[run.status]||run.status}}</strong><span>计划版本 {{run.revision}} · {{clock(run.at_seconds)}}</span></header>
        <p class="agent-workspace__goal">{{run.goal}}</p><p>{{run.reason}}</p>
        <p class="agent-workspace__meta">{{run.scope.building_name}} · {{run.summary.total}} 人 · {{run.planner_notice}}</p>
        <section v-if="coordination" class="agent-workspace__coordination" aria-label="智能体协同状态">
          <div class="agent-workspace__coordination-heading"><h4>当前协同</h4><span>现场 {{clock(coordination.at_seconds)}}</span></div>
          <ol class="agent-workspace__lanes">
            <li v-for="lane in coordination.lanes" :key="lane.id" :data-state="lane.state">
              <div><strong>{{lane.label}}</strong><span>{{laneLabels[lane.state]||lane.state}}</span></div><p>{{lane.detail}}</p>
            </li>
          </ol>
          <div class="agent-workspace__next">
            <p>{{coordination.next_action.reason}}</p>
            <button type="button" :disabled="busy||!!syncError" @click="nextAction">{{coordination.next_action.label}}<AppIcon name="arrowRight" :size="18" /></button>
          </div>
        </section>
        <p v-if="run.scope.robot_broadcast" class="agent-workspace__flow">居民分流与护送并行推进；机器人到位后广播，两条支线完成后核验清点。</p>
        <dl class="agent-workspace__counts"><div><dt>到集合点</dt><dd>{{run.summary.arrived}} / {{run.summary.total}}</dd></div><div><dt>已清点</dt><dd>{{run.summary.counted}}</dd></div><div><dt>已会合护送</dt><dd>{{run.summary.assisted}}</dd></div><div><dt>暴露超阈值</dt><dd>{{run.summary.exposed}}</dd></div></dl>
        <nav class="agent-workspace__tabs" aria-label="目标计划视图"><button v-for="tab in (['plan','execution','evidence'] as const)" :key="tab" type="button" :aria-pressed="detail===tab" @click="detail=tab">{{ ({plan:'方案',execution:'执行',evidence:'依据'})[tab] }}</button></nav>
        <section v-if="run.recovery" class="agent-workspace__recovery" aria-label="接续执行范围">
          <h4>从当前现场接续</h4>
          <p>{{clock(run.recovery.at_seconds)}} 重新比较时，保留 {{run.recovery.retained_arrived}} 名已到场人员，只调整 {{run.recovery.remaining}} 名未到场人员。{{run.recovery.active_escorts ? `${run.recovery.active_escorts} 名值守员继续原会合与护送，不重复占用岗位。` : ''}}</p>
          <p class="agent-workspace__meta">不回退人员位置、不重置烟气暴露和排队记录；{{run.status==='awaiting_approval'?'新方案仍需确认。':run.status==='needs_review'?'现场再次需要复核。':'行动进度按真实回执更新。'}}到场与清点进度以上方实时数据为准。</p>
        </section>
        <section v-if="detail==='plan'" aria-label="候选分流方案">
          <p v-if="run.status==='needs_review'" class="agent-workspace__notice">后续自动下令已暂停；下面保留的是原方案。请先“按当前现场重新比较”，不会取消已经受理的行动。</p>
          <p v-if="run.candidates.length" class="agent-workspace__meta">同一起点向后预演 30 秒。居民北侧蓝线、南侧金线，最多显示 48 条代表路线；机器人为紫线，箭头表示沿通道的前进方向。</p>
          <div class="agent-workspace__candidates">
            <article v-for="item in run.candidates" :key="item.id" :data-selected="candidate?.id===item.id">
              <label class="agent-workspace__check"><input type="radio" :name="'candidate-'+run.id" :value="item.id" v-model="chosen" :disabled="busy" /><strong>{{item.title}}</strong></label>
              <p v-if="candidate?.id!==item.id" class="agent-workspace__meta">北 {{item.metrics.north}} · 南 {{item.metrics.south}} · 不可达 {{item.metrics.unreachable}} 人；选中查看预演。</p>
              <template v-if="candidate?.id===item.id">
              <section v-if="item.allocation" class="agent-workspace__decision" aria-label="出口分配依据">
                <h4>为什么这样分流</h4><p>{{item.allocation.description}}</p>
                <p v-if="item.allocation.rule==='risk_capacity'" class="agent-workspace__meta">相对路径优先方案，{{item.allocation.changed_residents}} 人调整出口。{{item.allocation.same_allocation?'当前两种规则得到相同分配，不人为制造方案差异。':''}}</p>
                <p v-if="item.baseline_metrics" class="agent-workspace__meta">相对不下达本方案、沿用原安排：30 秒后到场 {{signed(item.metrics.arrived-item.baseline_metrics.arrived)}} 人，暴露超阈值 {{signed(item.metrics.exposed-item.baseline_metrics.exposed)}} 人，累计排队 {{signed(item.metrics.queue_seconds-item.baseline_metrics.queue_seconds)}} 人秒。</p>
                <details v-if="item.allocation.bottlenecks.length">
                  <summary>查看 {{item.allocation.bottlenecks.length}} 处共享通道压力</summary>
                  <ul><li v-for="place in item.allocation.bottlenecks" :key="place.edge_id">
                    <div><strong>{{place.name}}</strong><p>本方案途经 {{place.assigned}} 人 · 其他人员当前等待 {{place.waiting}} 人<br />通行能力 {{place.flow_capacity}} 人/秒 · 现场风险 {{place.risk_score}}/100</p></div>
                    <button type="button" :disabled="busy" @click="emit('focus',place.resident_id)">查看途经居民</button>
                  </li></ul>
                </details>
              </section>
              <dl><div><dt>出口分配</dt><dd>北 {{item.metrics.north}} · 南 {{item.metrics.south}}</dd></div><div><dt>不可达</dt><dd>{{item.metrics.unreachable}} 人</dd></div><div><dt>30 秒后到场</dt><dd>{{item.metrics.arrived}} 人</dd></div><div><dt>暴露超阈值</dt><dd>{{item.metrics.exposed}} 人</dd></div><div><dt>累计排队</dt><dd>{{item.metrics.queue_seconds}} 人秒</dd></div><div><dt>全场预测分</dt><dd>{{item.metrics.score}} <small>（{{item.metrics.score_delta>=0?'+':''}}{{item.metrics.score_delta}}）</small></dd></div></dl>
              <p v-if="item.assist_resource?.required" class="agent-workspace__resource-summary">需护送 {{item.assist_resource.required}} 人；本场 {{item.assist_resource.capacity}} 名值守员，{{item.assist_resource.busy}} 名正在执行。{{item.assist_resource.waves ? `至少分 ${item.assist_resource.waves} 批安排，实际等待取决于在途任务。` : '当前无可用值守员，不能执行护送。'}}</p>
              <section v-if="item.robot_support" class="agent-workspace__resource" aria-label="机器人协同条件">
                <h4><AppIcon name="robot" :size="18" />{{ item.robot_support.target }}</h4>
                <dl><div><dt>预计到位</dt><dd>{{ item.robot_support.already_completed ? '已完成广播' : item.robot_support.already_arrived ? '原任务已到位' : item.robot_support.duration_seconds === null ? '暂不可达' : item.robot_support.duration_seconds + ' 秒' }}</dd></div><div v-if="!item.robot_support.already_completed"><dt>{{item.robot_support.reusing_task ? '剩余电量需求 / 当前' : '电量需求 / 当前'}}</dt><dd>{{ item.robot_support.battery_required }} / {{ item.robot_support.battery_available ?? '—' }}</dd></div></dl>
                <p>{{ item.robot_support.notice }}</p>
              </section>
              <details v-if="item.geometry_issues?.length" class="agent-workspace__geometry">
                <summary>地图通行检查 · {{ item.geometry_issues.length }} 处不通行</summary>
                <p>这些连接与楼体相交，已从寻路中排除。请在地图编辑中调整，保存后新建场次；不能用“恢复道路”解除几何阻挡。</p>
                <ul><li v-for="issue in item.geometry_issues" :key="issue.edge_id"><strong>{{ issue.name }}</strong><span>{{ issue.reason }}</span></li></ul>
              </details>
              <p>{{item.reason}}</p><button type="button" :disabled="busy" @click="showRoute(item)"><AppIcon name="eye" :size="17" />在三维现场预览路线</button>
              </template>
            </article>
          </div>
          <p v-if="candidate" class="agent-workspace__meta">预演起点 {{clock(candidate.forecast_at)}} · {{candidate.coverage}}</p>
          <button v-if="run.candidates.length" type="button" @click="emit('preview',[])">清除现场方案路线</button>
          <div class="agent-workspace__actions">
            <button v-if="run.status==='awaiting_approval'" type="button" class="agent-workspace__primary" :disabled="busy||!live||!candidate?.can_apply||!!syncError||run.approval_guard?.can_approve===false" @click="act('approve')">确认方案并执行</button>
            <button v-if="['awaiting_approval','needs_review'].includes(run.status)" type="button" :disabled="busy||drillStatus==='ended'" @click="act('replan')">按当前现场重新比较</button>
          </div>
          <p v-if="run.approval_guard?.needs_replan" class="agent-workspace__notice">{{run.approval_guard.reason}} 原预演保留用于对照，重新比较后需再次确认。</p>
          <p v-if="!live&&run.status==='awaiting_approval'" class="agent-workspace__notice">请先开始或继续演练，再确认执行。</p>
          <p v-if="!run.candidates.length">{{run.scope.completion}}</p>
        </section>
        <section v-else-if="detail==='execution'" aria-label="目标执行步骤">
          <p v-if="run.decision" class="agent-workspace__meta">执行依据：{{run.decision.title}} · 批准版本 {{run.decision.revision}} · {{clock(run.decision.approved_at)}} 确认。完整分流依据保留在“依据”中。</p>
          <button v-if="run.outcomes?.length" type="button" class="agent-workspace__disclosure" @click="detail='evidence'">{{run.outcomes[0]?.result?'查看预测与实际结果差异':`查看 ${clock(run.outcomes[0]!.due_seconds)} 结果核对计划`}}<AppIcon name="arrowRight" :size="18" /></button>
          <section v-if="coordination && (coordination.issues.length || coordination.bottlenecks.length)" class="agent-workspace__attention" aria-label="需要关注的现场">
            <h4>先看这些现场</h4>
            <p v-if="(coordination.issue_count??0)>coordination.issues.length" class="agent-workspace__meta">共 {{coordination.issue_count}} 项人员风险，优先列出 {{coordination.issues.length}} 项；全部目标人员持续接受监护。</p>
            <ul><li v-for="issue in coordination.issues" :key="issue.id"><div><strong>{{issue.label}}</strong><p>{{issue.reason}}</p></div><button type="button" @click="emit('focus',issue.resident_id)"><AppIcon name="target" :size="18" />定位</button></li>
            <li v-for="place in coordination.bottlenecks" :key="place.edge_id"><div><strong>{{place.name}}</strong><p>{{place.waiting}} 人等待 · 最长累计排队 {{place.max_wait_seconds}} 秒</p></div><button type="button" @click="emit('focus',place.resident_id)">查看队列</button></li></ul>
          </section>
          <section v-if="coordination?.robot.included" class="agent-workspace__robot-live" aria-label="机器人实时执行">
            <div><h4><AppIcon name="robot" :size="18" />机器人协同</h4><button type="button" @click="emit('robot')">查看三维位置</button></div>
            <p>{{coordination.robot.reason||'等待机器人状态回执'}} · 电量 {{coordination.robot.battery??'—'}}%</p>
            <p class="agent-workspace__meta">到位与广播步骤已完成 {{coordination.robot.steps_completed}} / {{coordination.robot.steps_total}}</p>
          </section>
          <p v-if="run.execution" class="agent-workspace__meta">现场同步 {{clock(run.execution.at_seconds)}} · 事件 {{run.execution.event_sequence}}。展开步骤可定位受阻人员与查看执行依据。</p>
          <p v-if="['stopped','taken_over'].includes(run.status)" class="agent-workspace__notice">自动下令已停止；下方继续显示已受理指令的实际进展。</p>
          <p v-if="!run.steps.length">方案确认后，这里显示命令进度与等待原因。</p>
          <p v-else class="agent-workspace__meta" role="status">已完成 {{ stepSummary.completed }} / {{ stepSummary.total }} 项；步骤完成依据来自实际命令回执。</p>
          <ol class="agent-workspace__steps">
            <li v-for="step in run.steps" :key="step.id">
              <div class="agent-workspace__step-heading"><strong>{{step.label}}</strong><span>{{labels[step.status]||step.status}}</span></div>
              <p v-if="dependencyLabel(step)" class="agent-workspace__meta">前置步骤：{{ dependencyLabel(step) }}</p>
              <progress :value="step.progress" max="1" :aria-label="step.label+'进度'" />
              <p>{{step.reason}}</p>
              <p v-if="step.execution?.stalled" class="agent-workspace__notice">已 {{step.execution.idle_seconds}} 秒未观察到位置或命令进度变化，请定位现场检查。原指令继续保留。</p>
              <button v-if="step.resident_ids.length" type="button" @click="emit('focus',step.resident_ids[0]!)">定位这组居民</button>
              <button v-else-if="step.kind==='robot.command'" type="button" @click="emit('robot')">定位机器人</button>
              <template v-if="step.execution">
                <p v-if="step.execution.total" class="agent-workspace__meta">到场 {{step.execution.arrived}} / {{step.execution.total}} · 受阻 {{step.execution.blocked}} · 正在排队 {{step.execution.queued}}</p>
                <button type="button" class="agent-workspace__disclosure" :aria-expanded="expandedStep===step.id" :aria-controls="`step-detail-${step.id}`" @click="expandedStep=expandedStep===step.id?'':step.id">{{expandedStep===step.id?'收起':'查看'}}人员与执行依据 <AppIcon name="chevron" :size="18" /></button>
                <div v-if="expandedStep===step.id" :id="`step-detail-${step.id}`" class="agent-workspace__detail">
                  <ul class="agent-workspace__people">
                    <li v-for="person in step.execution.attention" :key="person.id">
                      <div><strong>{{person.label}}</strong><button type="button" :aria-label="`定位${person.label}`" @click="emit('focus',person.id)"><AppIcon name="target" :size="16" />定位</button></div>
                      <p>{{person.behavior}}<br /><span>{{person.location}}</span></p>
                      <p v-if="person.bottleneck&&!person.arrived" class="agent-workspace__meta">当前通道：{{person.bottleneck}} · 累计排队 {{person.queue_seconds}} 秒</p>
                      <p v-if="person.staff_name" class="agent-workspace__meta">{{person.staff_name}} · {{person.responsible||'模拟值守岗位'}} · {{({approaching:'前往会合',escorting:'已经会合，同行中',blocked:'会合路线受阻',completed:'护送结束'} as Record<string,string>)[person.escort_state??'']||'待会合'}}</p>
                    </li>
                  </ul>
                  <p v-if="step.execution.remaining_details" class="agent-workspace__meta">另有 {{step.execution.remaining_details}} 人；优先展示受阻、未到场和高暴露人员，全部人员仍参与执行。</p>
                  <p v-if="!step.execution.command_recorded" class="agent-workspace__meta">尚未下达领域指令，正在等待执行条件。</p>
                  <ol v-else class="agent-workspace__evidence"><li v-for="item in step.execution.evidence" :key="item.id"><time>{{clock(item.at_seconds)}}</time><p>{{item.message}}<span class="agent-workspace__meta"> · 事件 {{item.sequence}}</span></p></li></ol>
                </div>
              </template>
            </li>
          </ol>
          <button v-if="run.status==='awaiting_rollcall'" type="button" @click="emit('rollcall')">前往集合清点</button>
        </section>
        <section v-else aria-label="计划过程证据">
          <section v-if="run.decision" class="agent-workspace__decision" aria-label="已批准决策依据">
            <h4>{{run.decision.title}} · 版本 {{run.decision.revision}}</h4>
            <p>{{clock(run.decision.approved_at)}} 人工确认，预演起点 {{clock(run.decision.forecast_at)}}。</p>
            <p v-if="run.decision.allocation">{{run.decision.allocation.description}}</p>
            <p class="agent-workspace__meta">当时向后预演 {{run.decision.forecast_seconds}} 秒：预计到场 {{run.decision.metrics.arrived}} 人、暴露超阈值 {{run.decision.metrics.exposed}} 人、累计排队 {{run.decision.metrics.queue_seconds}} 人秒。此处保留批准时的预测，实际进展见“执行”。</p>
          </section>
          <AgentOutcomeReview v-if="run.outcomes?.length" :outcomes="run.outcomes" :elapsed="run.at_seconds" @replay="at=>emit('replay',at)" />
          <p>{{run.scope.completion}}</p><ol class="agent-workspace__evidence"><li v-for="item in run.history" :key="item.id"><time>{{clock(item.at_seconds)}}</time><p>{{item.message}}</p></li></ol>
        </section>
        <div v-if="!canCreate" class="agent-workspace__stop">
          <div class="agent-workspace__control-actions">
            <button v-if="['executing','waiting','paused'].includes(run.status)" type="button" :disabled="busy||!!syncError" @click="act('review')"><AppIcon name="route" :size="18" />调整剩余行动</button>
            <button type="button" :disabled="busy" @click="act('stop')">{{run.steps.length?'停止后续自动下令':'取消未执行方案'}}</button>
          </div>
          <p>调整只暂停后续自动下令，已受理动作仍继续；重新比较后需再次确认。暂停整个现场请使用顶部“暂停演练”；人工改派后，本计划会让出控制。</p>
        </div>
      </article>
    </template>
  </section>
</template>

<style scoped>
.agent-workspace{min-width:0;font-size:16px;line-height:1.65;color:#e9f1e8}
.agent-workspace h3{font-size:20px;margin:0 0 8px}.agent-workspace p{margin:8px 0 12px;overflow-wrap:anywhere}
.agent-workspace__intro{padding-bottom:16px;border-bottom:1px solid #335347;margin-bottom:18px}
.agent-workspace__sync{display:flex;align-items:center;gap:var(--space-2);font-size:14px;color:var(--text-secondary)}
.agent-workspace__sync svg{flex-shrink:0}
.agent-workspace__geometry{margin-block:16px;border-block:1px solid #65836a;padding-block:8px;min-width:0}
.agent-workspace__geometry summary{min-height:44px;align-content:center;cursor:pointer;color:#f0d6a3;overflow-wrap:anywhere}
.agent-workspace__geometry ul{max-height:240px;overflow:auto;margin:0;padding-inline-start:22px}
.agent-workspace__geometry li{padding-block:8px;overflow-wrap:anywhere}
.agent-workspace__geometry li span{display:block;color:#c1d3c4}
.agent-workspace__form{display:grid;gap:14px}.agent-workspace label{display:grid;gap:8px;min-width:0}
.agent-workspace :is(textarea,select){width:100%;min-width:0;min-height:44px;border:1px solid #65836a;border-radius:6px;padding:10px;background:#0d241f;color:#edf5e7;font:inherit}
.agent-workspace textarea{height:auto;max-height:140px;resize:vertical}
.agent-workspace .agent-workspace__check{display:flex;align-items:center;gap:10px;min-height:44px;cursor:pointer}
.agent-workspace__check input{width:20px;height:20px;margin:0;flex-shrink:0;accent-color:#b4ddb1}
.agent-workspace .agent-workspace__primary{background:#d8e8bb;color:#173d2a;border-color:transparent;width:100%}
.agent-workspace__meta,.agent-workspace__run>header span{font-size:14px;color:#c1d3c4}
.agent-workspace__error,.agent-workspace__notice{padding:12px;background:#263d30;border:1px solid #84977a;border-radius:6px;color:#f2e6bf}
.agent-workspace__error{border-color:#b58064;color:#ffd0b8}
.agent-workspace__run{margin-top:20px;padding-top:20px;border-top:1px solid #476653}
.agent-workspace__run>header{display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px}.agent-workspace__run>header strong{font-size:18px;color:#cce9a9}
.agent-workspace__goal{font-weight:600}
.agent-workspace__resource-option{padding-block:var(--space-2);border-block:1px solid var(--border-default)}
.agent-workspace__resource-option p{margin:0}
.agent-workspace__flow{padding-block:var(--space-3);border-block:1px solid var(--border-default);color:var(--text-primary)}
.agent-workspace__resource{margin-top:var(--space-4);padding-top:var(--space-3);border-top:1px solid var(--border-default)}
.agent-workspace__resource h4{display:flex;align-items:flex-start;gap:var(--space-2);margin:0;font-size:16px;overflow-wrap:anywhere}
.agent-workspace__resource h4 svg{flex-shrink:0;margin-top:4px}
.agent-workspace__resource p{font-size:14px;color:var(--text-secondary)}
.agent-workspace :is(dt,dd){min-width:0;overflow-wrap:anywhere}
.agent-workspace dl{margin:12px 0;display:grid;gap:8px}.agent-workspace dl>div{display:flex;justify-content:space-between;gap:12px}.agent-workspace dt{color:#c1d3c4}.agent-workspace dd{margin:0;text-align:right;font-variant-numeric:tabular-nums}
.agent-workspace .agent-workspace__counts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;padding:12px 0;border-block:1px solid #335347}
.agent-workspace__counts>div{display:block!important}.agent-workspace__counts dd{text-align:left;font-size:20px}
.agent-workspace__tabs{display:flex;gap:6px;margin:18px 0}.agent-workspace__tabs button{flex:1;background:transparent}.agent-workspace__tabs button[aria-pressed=true]{background:#315647;border-color:#a4c5a1}
.agent-workspace__candidates{display:grid;gap:18px}.agent-workspace__candidates>article{padding:14px;border:1px solid #476653;border-radius:8px}.agent-workspace__candidates>article[data-selected=true]{border-color:#b6d6a6}.agent-workspace__candidates button{width:100%}
.agent-workspace__actions{display:grid;gap:10px;margin-top:16px}.agent-workspace__steps{padding:0;list-style:none;margin:0}.agent-workspace__steps>li{padding:16px 0;border-bottom:1px solid #335347}.agent-workspace__step-heading{display:flex;flex-wrap:wrap;gap:6px 14px;justify-content:space-between}.agent-workspace__steps span{font-size:14px;color:#cce9a9}.agent-workspace progress{display:block;width:100%;height:6px;margin:12px 0;accent-color:#b4ddb1}
.agent-workspace__evidence{padding:0;list-style:none}.agent-workspace__evidence>li{display:grid;grid-template-columns:56px minmax(0,1fr);gap:10px;padding:10px 0;border-bottom:1px solid #335347}.agent-workspace__evidence time{font-size:14px;color:#b4ddb1;font-variant-numeric:tabular-nums}.agent-workspace__evidence p{margin:0}
.agent-workspace__stop{margin-top:22px;padding-top:16px;border-top:1px solid #476653}.agent-workspace__stop p{font-size:14px;color:#c1d3c4}.agent-workspace__stop button{width:100%}
.agent-workspace__control-actions{display:flex;flex-wrap:wrap;gap:var(--space-3)}
.agent-workspace__control-actions button{flex:1 1 200px;min-width:0;min-height:44px;display:flex;align-items:center;justify-content:center;gap:var(--space-2);white-space:normal}
.agent-workspace__recovery{margin-block:var(--space-4);padding-block:var(--space-3);border-block:1px solid var(--border-default)}
.agent-workspace__decision{padding-block:var(--space-3);margin-bottom:var(--space-3);border-bottom:1px solid var(--border-default)}
.agent-workspace__decision summary{min-height:44px;align-content:center;cursor:pointer;overflow-wrap:anywhere}
.agent-workspace__decision ul{list-style:none;padding:0;margin:var(--space-2) 0}
.agent-workspace__decision li{min-width:0;padding-block:var(--space-3);border-top:1px solid var(--border-default)}
.agent-workspace__decision li p{font-size:14px;color:var(--text-secondary)}
.agent-workspace__decision button{min-height:44px;white-space:normal}
.agent-workspace__resource-summary{padding-block:var(--space-3);border-block:1px solid var(--border-default);font-size:14px;color:var(--text-secondary)}
.agent-workspace__disclosure{width:100%;display:flex;align-items:center;justify-content:space-between;gap:var(--space-2);margin-block:var(--space-3);min-height:44px;text-align:left}
.agent-workspace__disclosure svg{flex-shrink:0}
.agent-workspace__disclosure[aria-expanded=true] svg{transform:rotate(180deg)}
.agent-workspace__detail{min-width:0;padding-block:var(--space-2)}
.agent-workspace__people{margin:0;padding:0;list-style:none}
.agent-workspace__people>li{padding-block:var(--space-3);border-top:1px solid var(--border-default)}
.agent-workspace__people>li>div{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:var(--space-2)}
.agent-workspace__people button{min-height:44px;flex-shrink:0}
.agent-workspace__people p{margin-block:var(--space-2)}
.agent-workspace__people p span{color:var(--text-secondary);font-size:14px}
.agent-workspace :is(button,strong){overflow-wrap:anywhere}
.agent-workspace__step-heading>strong{flex:1 1 180px;min-width:0}
.agent-workspace__detail .agent-workspace__evidence{margin-block:var(--space-3)}
.agent-workspace__coordination{margin-block:var(--space-5);padding-block:var(--space-4);border-block:1px solid var(--border-default)}
.agent-workspace__coordination-heading,.agent-workspace__lanes li>div,.agent-workspace__robot-live>div{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:var(--space-2)}
.agent-workspace h4{margin:0;font-size:16px}
.agent-workspace__coordination-heading>span,.agent-workspace__lanes li>div>span{font-size:14px;color:var(--text-secondary)}
.agent-workspace__lanes{margin:var(--space-3) 0;padding:0;list-style:none;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--space-4)}
.agent-workspace__lanes li{min-width:0;padding-top:var(--space-3);border-top:1px solid var(--border-default)}
.agent-workspace__lanes p{font-size:14px;margin:var(--space-2) 0 0;color:var(--text-secondary)}
.agent-workspace__lanes li[data-state=attention] strong,.agent-workspace__lanes li[data-state=review] strong{color:var(--status-warning)}
.agent-workspace__next{margin-top:var(--space-4)}
.agent-workspace__next button{width:100%;min-height:44px;display:flex;align-items:center;justify-content:space-between;gap:var(--space-3);white-space:normal;text-align:left}
.agent-workspace__attention{margin-block:var(--space-4)}
.agent-workspace__attention ul{list-style:none;padding:0;margin:0}
.agent-workspace__attention li{display:flex;align-items:center;gap:var(--space-3);padding-block:var(--space-3);border-bottom:1px solid var(--border-default)}
.agent-workspace__attention li>div{flex:1;min-width:0}.agent-workspace__attention li p{margin:var(--space-1) 0 0;font-size:14px;color:var(--text-secondary)}
.agent-workspace__attention button{flex-shrink:0;min-height:44px;display:flex;align-items:center;gap:var(--space-1)}
.agent-workspace__robot-live{padding-block:var(--space-4);margin-bottom:var(--space-4);border-block:1px solid var(--border-default)}
.agent-workspace__robot-live h4{display:flex;align-items:center;gap:var(--space-2)}
@media(max-width:480px){.agent-workspace__lanes{grid-template-columns:minmax(0,1fr);gap:var(--space-3)}.agent-workspace__attention li{align-items:flex-start;flex-wrap:wrap}.agent-workspace__attention li>div{flex-basis:100%}}
</style>
