<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { createApiClient } from '../api/client'
import { canApplyAgentRun, type AgentAssignment, type AgentCandidate, type AgentRun, type AgentLiveState } from '../domain/agent'
import AppIcon from './AppIcon.vue'
import AgentOutcomeReview from './AgentOutcomeReview.vue'
import SpeechInput from './SpeechInput.vue'
import KnowledgeEvidence from './KnowledgeEvidence.vue'
import AgentPlanningEvidence from './AgentPlanningEvidence.vue'
import AgentRevisionView from './AgentRevisionView.vue'
import SpeechPlayback from './SpeechPlayback.vue'

const props = defineProps<{ apiBaseUrl:string;accessToken:string;drillId:string;active:boolean;historical:boolean;modelAvailable:boolean;focusId?:string;liveFeed?:AgentLiveState|null;connection?:'connecting'|'live'|'stale';goalDraft?:{id:number;text:string}|null;planFocus?:{id:string;request:number}|null }>()
const emit = defineEmits<{ preview:[people:AgentAssignment[]];residentFocus:[id:string];buildingFocus:[id:string];robot:[];vehicle:[];rollcall:[];missions:[];task:[id:string];indoor:[doorId?:string];replay:[at:number];knowledge:[id:string,version?:string,chunk?:string] }>()
const api = createApiClient(props.apiBaseUrl, () => props.accessToken)
const goal = ref('将目标居民分流疏散，重点人员安排护送'), building = ref(''), assist = ref(true), useModel = ref(false)
const robotBroadcast = ref(false)
const floorInput=ref(''), objective=ref('balanced'), forbiddenExits=ref<string[]>([]), voiceBusy=ref(false)
const revisionObjective=ref('balanced'), revisionExits=ref<string[]>([]), revisionModel=ref(false)
const expandedStep = ref('')
const workspace=ref<HTMLElement|null>(null)
async function openOutcomeEvidence() {
  detail.value='evidence'
  await nextTick()
  workspace.value?.querySelector('.agent-outcome')?.scrollIntoView({block:'nearest'})
}
const buildings = ref<Array<{id:string;name:string}>>([]), runs = ref<AgentRun[]>([]), drillStatus = ref('')
const loading = ref(false), busy = ref(false), error = ref(''), syncError = ref(''), chosen = ref(''), detail = ref<'plan'|'execution'|'evidence'>('plan')
let timer:ReturnType<typeof setTimeout>|undefined, generation=0, pollEpoch=0, requestId='', disposed=false
let readController:AbortController|null=null
const selectedRunId = ref('')
const composing = ref(false)
let appliedDraft=0
let appliedFocus=0
const run = computed(() => runs.value.find(item=>item.id===selectedRunId.value) ?? runs.value[0])
const streamReady=computed(()=>props.connection==='live' && props.liveFeed?.id===props.drillId)
const syncLabel=computed(()=>drillStatus.value==='ended'?'本场结果已冻结，计划与证据保持只读':streamReady.value?'与三维现场实时联动':props.connection==='stale'?'连接恢复中，定时核对最近状态':'正在连接现场，暂用状态读取')
const coordination = computed(() => run.value?.execution?.coordination)
const executionSpeech=computed(()=>run.value?`${run.value.scope.building_name}，目标 ${run.value.summary.total} 人，已到场 ${run.value.summary.arrived} 人，已清点 ${run.value.summary.counted} 人。${run.value.reason}${coordination.value?.next_action.reason||''}`:'')
const laneLabels:Record<string,string> = { observing:'持续核对',paused:'现场冻结',review:'需要复核',approval:'待人工确认',confirmed:'已确认',waiting:'等待条件',attention:'需要关注' }
const candidate = computed(() => run.value?.candidates.find(p => p.id===chosen.value) ?? run.value?.candidates[0])
const live = computed(() => !props.historical && ['running','paused'].includes(drillStatus.value))
const canCreate = computed(() => composing.value || !run.value)
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
  else if (action.kind==='missions' && action.task_id) emit('task',action.task_id)
  else if (action.kind==='missions') emit('missions')
  else if (action.kind==='indoor') emit('indoor',action.door_id)
  else if (action.kind==='robot') emit('robot')
  else if (action.kind==='vehicle') emit('vehicle')
  else if (action.kind==='focus' && action.resident_id) emit('residentFocus', action.resident_id)
  else if(action.kind!=='review'&&run.value?.status==='completed') void openOutcomeEvidence()
  else detail.value=action.kind==='review'?'plan':'execution'
}
function focusResource(key:string) {
  if(key.startsWith('robot:')){emit('robot');return}
  if(key.startsWith('vehicle:')){emit('vehicle');return}
  const person=run.value?.execution?.staff.find(staff=>key==='staff:'+staff.id)?.resident_id
  if(person)emit('residentFocus',person)
}
function setRun(value:AgentRun) {
  if(value.drill_status)drillStatus.value=value.drill_status
  const changed = run.value?.id !== value.id
  runs.value = [value,...runs.value.filter(r => r.id!==value.id)]
  if(!selectedRunId.value || changed)selectedRunId.value=value.id
  if (changed || !value.candidates.some(p => p.id===chosen.value)) chosen.value=value.planning?.recommended_candidate_id ?? value.candidates[0]?.id ?? ''
  if (changed) detail.value=value.steps.length?'execution':'plan'
  if (!value.steps.some(step => step.id===expandedStep.value)) expandedStep.value=(value.steps.find(step=>['blocked','waiting','executing'].includes(step.status))??value.steps[0])?.id??''
}
function applyStream() {
  if(!streamReady.value || !props.liveFeed || !props.active || props.historical || busy.value || disposed)return
  const value=props.liveFeed, incoming=value.runs.find(r=>r.id===run.value?.id) ?? value.runs[0]
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
    const incoming=value.runs.find(r=>r.id===run.value?.id)??value.runs[0]
    if(incoming)setRun(incoming)
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
  if (goal.value.length > 2000) { error.value = '目标超过 2000 字，请编辑缩短后再生成方案。'; return }
  if(busy.value || voiceBusy.value || props.historical || !goal.value.trim())return
  const floors=floorInput.value.trim()?floorInput.value.split(/[\s,，、]+/).map(Number):[]
  if(floors.some(value=>!Number.isInteger(value)||value<1||value>100)||floors.length>30){error.value='楼层请输入 1–100 的整数，多层用逗号分隔，最多 30 层。';return}
  busy.value=true;error.value='';generation++;readController?.abort();const version=generation,scope=props.drillId
  requestId ||= globalThis.crypto?.randomUUID?.() ?? `goal-${Date.now()}-${Math.random().toString(36).slice(2)}`
  try {
    const value=await api.post<AgentRun>(`/drills/${scope}/agent/runs`,{request_id:requestId,goal:goal.value,building_id:building.value||null,resident_ids:!building.value&&props.focusId?.startsWith('resident-')?[props.focusId]:[],priority_assist:assist.value,robot_broadcast:robotBroadcast.value,pause_for_review:true,include_case_tasks:true,use_model:useModel.value&&props.modelAvailable,floors,objective:objective.value,forbidden_exits:forbiddenExits.value},{signal:AbortSignal.timeout(60000)})
    if(version!==generation||disposed)return
    setRun(value);detail.value='plan';requestId='';composing.value=false
  } catch(cause){if(version===generation)error.value=cause instanceof Error?cause.message:'方案生成失败，请重试。'}
  finally{if(version===generation)busy.value=false}
}
async function act(action:'approve'|'stop'|'replan'|'review') {
  if(!run.value||busy.value||props.historical)return
  if(action==='replan'&&new Set(revisionExits.value).size===2){error.value='两个出口均被禁止，请先调整约束或处理通道。';return}
  generation++;readController?.abort();const current=run.value,version=generation;busy.value=true;error.value=''
  try{
    const value=await api.post<AgentRun>(`/drills/${props.drillId}/agent/runs/${current.id}/actions`,{action,revision:current.revision,candidate_id:action==='approve'?candidate.value?.id:null,...(action==='replan'?{objective:revisionObjective.value,forbidden_exits:revisionExits.value,use_model:revisionModel.value&&props.modelAvailable}:{})},{signal:AbortSignal.timeout(action==='replan'?60000:30000)})
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
watch([goal,building,assist,useModel,robotBroadcast,floorInput,objective,forbiddenExits,()=>props.focusId],()=>{requestId=''},{deep:true})
watch([()=>run.value?.id,()=>run.value?.revision],()=>{
  revisionObjective.value=run.value?.scope.objective||'balanced';revisionExits.value=[...(run.value?.scope.forbidden_exits||[])];revisionModel.value=false
},{immediate:true})
watch([()=>props.planFocus,runs],([focus])=>{
  if(!focus||focus.request===appliedFocus||!runs.value.some(item=>item.id===focus.id))return
  appliedFocus=focus.request;selectedRunId.value=focus.id;composing.value=false
},{immediate:true})
watch([()=>props.goalDraft,busy],([draft,isBusy])=>{
  if(!draft||isBusy||draft.id===appliedDraft)return
  appliedDraft=draft.id;goal.value=draft.text;composing.value=!!run.value;detail.value='plan'
  building.value='';floorInput.value='';objective.value='balanced';forbiddenExits.value=[];assist.value=true;robotBroadcast.value=false
},{immediate:true})
watch([()=>props.liveFeed,streamReady,()=>props.active,()=>props.historical,busy],applyStream,{flush:'post'})
watch(chosen,()=>emit('preview',[]),{flush:'sync'})
watch(()=>props.drillId,()=>{runs.value=[];buildings.value=[];chosen.value='';expandedStep.value='';building.value='';floorInput.value='';objective.value='balanced';forbiddenExits.value=[];requestId='';error.value='';syncError.value='';drillStatus.value=''})
watch(selectedRunId,()=>{chosen.value=run.value?.planning?.recommended_candidate_id??run.value?.candidates[0]?.id??'';expandedStep.value='';emit('preview',[]);detail.value=run.value?.steps.length?'execution':'plan'})
watch([()=>props.active,()=>props.historical,()=>props.drillId],()=>{
  generation++;pollEpoch++;busy.value=false;loading.value=false;readController?.abort();clearTimeout(timer)
  if(props.historical)emit('preview',[])
  if(props.active&&!props.historical){const epoch=pollEpoch;void read(true).then(()=>{if(epoch===pollEpoch&&!disposed)timer=setTimeout(()=>poll(epoch),3000)})}
},{immediate:true})
onBeforeUnmount(()=>{disposed=true;generation++;pollEpoch++;clearTimeout(timer);readController?.abort();emit('preview',[])})
</script>

<template>
  <section ref="workspace" class="agent-workspace" aria-label="疏散目标计划" :aria-busy="busy||loading">
    <p v-if="historical" class="agent-workspace__notice">正在查看历史现场。返回实时现场后可制定或执行目标计划，历史解读仍在对话中查看。</p>
    <template v-else>
      <div class="agent-workspace__intro"><h3>{{run?'本场目标与执行':'建立疏散目标'}}</h3><p>方案由你确认，执行进展以现场回执为准。</p><details><summary>协同方式与人工确认规则</summary><p>目标解析 → 仿真比较 → 人工确认 → 工具执行 → 结果核对。生成与重算方案会暂停现场，确认执行后继续。燃气、电源和证据核验由责任人操作。</p></details></div>
      <p v-if="connection" class="agent-workspace__sync" role="status"><AppIcon :name="drillStatus==='ended'?'tasks':streamReady?'pulse':'refresh'" :size="17" />{{syncLabel}}</p>
      <p v-if="syncError" class="agent-workspace__error" role="alert">{{syncError}} <button type="button" @click="read(true)">重新连接</button></p>
      <p v-if="loading&&!run" role="status">正在恢复本场目标计划…</p>
      <button v-if="!canCreate && !loading && drillStatus!=='ended'" type="button" :disabled="busy" @click="composing=true">另建独立范围目标</button>
      <p v-if="!run&&!loading&&drillStatus==='ended'" class="agent-workspace__meta">本场没有目标计划记录。可查看事件与评分；新开训练后再建立目标。</p>
      <button v-if="composing" type="button" @click="composing=false">返回当前计划</button>
      <section v-if="run?.task_graph?.case_tasks?.length" class="agent-workspace__case-tasks" aria-label="案例责任任务">
        <div class="agent-workspace__case-heading"><h4>案例处置 · {{run.task_graph.case_tasks.length}} 项</h4><button type="button" @click="emit('missions')">查看与核验</button></div>
        <p>{{run.task_graph.case_tasks.filter(task=>task.state!=='completed').length}} 项待核验<template v-if="run.task_graph.case_tasks.some(task=>task.verification_ready)">，已有任务满足提交条件</template>。</p>
        <details><summary>查看责任人与截止时间</summary>
        <button v-for="task in run.task_graph.case_tasks" :key="task.id" type="button" :data-ready="task.verification_ready||undefined" :data-overdue="task.overdue||undefined" @click="emit('task',task.id)">
          <strong>{{task.label}}</strong>
          <span>{{task.state==='completed'?(task.completed_on_time===false?'超时核验 · 证据已留存':'已核验'):task.verification_ready?'立即核验':task.overdue?'已超时，可补救':`剩余 ${task.remaining_seconds ?? '—'} 秒`}} · {{task.responsible_role}}</span>
          <small v-if="task.state!=='completed'">下一步：{{task.next_required_action}}</small>
          <small v-if="task.depends_on?.length">关联行动：{{dependencyLabel(task)}}</small>
        </button>
        </details>
      </section>
      <label v-if="runs.length>1" class="agent-workspace__plan-select">当前计划<select v-model="selectedRunId" :disabled="busy"><option v-for="item in runs" :key="item.id" :value="item.id">{{labels[item.status]||item.status}} · {{item.scope.building_name}} · {{item.goal}}</option></select></label>
      <form v-if="canCreate&&!loading&&drillStatus!=='ended'" class="agent-workspace__form" @submit.prevent="create">
        <SpeechInput v-if="active" :key="drillId" :api-base-url="apiBaseUrl" :access-token="accessToken" :disabled="busy" destination="目标框" @activity="value=>voiceBusy=value" @transcript="text=>goal=goal.trim() ? goal.trimEnd()+'\n'+text : text" />
        <label>演练目标<textarea v-model="goal" rows="3" maxlength="2000" :disabled="busy" placeholder="例如：将三号楼居民分流疏散，并护送重点人员" /></label>
        <label>目标范围<select v-model="building" aria-label="目标范围" :disabled="busy"><option value="">{{focusId?.startsWith('resident-')?'当前选中居民':'全部待撤离居民（或按目标解析建筑）'}}</option><option v-for="item in buildings" :key="item.id" :value="item.id">{{item.name}}</option></select></label>
        <details class="agent-workspace__constraints"><summary>目标约束与优化取向</summary>
          <div class="agent-workspace__constraint-fields"><label>居住楼层（可选）<input v-model="floorInput" :disabled="busy" placeholder="例如：3，4；留空按目标解析" maxlength="120"/></label>
          <label>方案优化取向<select v-model="objective" aria-label="方案优化取向" :disabled="busy"><option value="balanced">风险与效率均衡</option><option value="low_exposure">优先降低暴露</option><option value="fast_arrival">优先尽快到场</option></select></label></div>
          <fieldset :disabled="busy"><legend>禁止使用的出口</legend><label class="agent-workspace__check"><input v-model="forbiddenExits" type="checkbox" value="north"/>北侧出口</label><label class="agent-workspace__check"><input v-model="forbiddenExits" type="checkbox" value="south"/>南侧出口</label></fieldset>
          <p class="agent-workspace__meta">按冻结的居住楼层确定人员，移动途中名单保持不变。约束参与路径和仿真计算；不可达时不自动放宽禁用条件。</p>
        </details>
        <label class="agent-workspace__check"><input type="checkbox" v-model="assist" :disabled="busy" />重点人员安排护送</label>
        <div class="agent-workspace__resource-option">
          <label class="agent-workspace__check"><input type="checkbox" v-model="robotBroadcast" :disabled="busy" />机器人到楼门广播</label>
          <p class="agent-workspace__meta">选择单栋时直达该楼门；选择全部居民时按涉及楼栋拆成顺序任务。居民撤离并行，机器人每次真实到位后才广播。</p>
        </div>
        <label v-if="modelAvailable" class="agent-workspace__check"><input type="checkbox" v-model="useModel" :disabled="busy" />授权模型读取目标、精简现场、知识片段与工具结果并推荐方案</label>
        <p class="agent-workspace__meta">{{useModel&&modelAvailable?'模型解析目标，本地校验和仿真规划。':'本地目标解析与仿真规划，不调用大模型。'}} 生成方案不会下达指令。</p>
        <button type="submit" class="agent-workspace__primary" :disabled="busy||voiceBusy||!goal.trim()||drillStatus==='ended'"><AppIcon name="route" :size="18" />{{busy?'正在核对依据与比较方案…':voiceBusy?'等待语音识别完成':'生成并比较方案'}}</button>
      </form>
      <p v-if="error" class="agent-workspace__error" role="alert">{{error}}</p>
      <article v-if="run" class="agent-workspace__run">
        <header><strong>{{labels[run.status]||run.status}}</strong><span>计划版本 {{run.revision}} · {{clock(run.at_seconds)}}</span></header>
        <p class="agent-workspace__goal"><span v-if="run.revision_context" class="agent-workspace__meta">原始目标 · </span>{{run.goal}}</p><p>{{run.reason}}</p>
        <AgentRevisionView :run="run" :candidate-id="candidate?.id" @focus="id=>emit('residentFocus',id)" @robot="emit('robot')" @replay="seconds=>emit('replay',seconds)"/>
        <p class="agent-workspace__meta">{{run.scope.building_name}} · {{run.summary.total}} 人 · {{run.planner_notice}}</p>
        <button v-if="run.scope.resident_ids.length" type="button" @click="emit('residentFocus',run.scope.resident_ids[0]!)"><AppIcon name="target" :size="18"/>查看目标现场</button>
        <p v-if="run.scope.floors?.length || run.scope.forbidden_exits?.length" class="agent-workspace__meta">{{run.scope.floors?.length?`目标楼层：${run.scope.floors.join('、')}层。`:''}}{{run.scope.forbidden_exits?.length?`禁用：${run.scope.forbidden_exits.map(exit=>exit==='north'?'北侧出口':'南侧出口').join('、')}。`:''}}</p>
        <AgentPlanningEvidence v-if="run.planning" :report="run.planning" :approved="Boolean(run.approved_revision)"/>
        <details v-if="run.knowledge" class="agent-workspace__knowledge"><summary>方案参考资料 · {{run.knowledge.hits.length}} 条</summary><p>以下是制定目标时检索到的资料；路线、资源和动作可行性由仿真工具校验。</p><KnowledgeEvidence :result="run.knowledge" @open="source=>emit('knowledge',source.documentId,source.versionId,source.chunkId)"/></details>
        <section v-if="coordination" class="agent-workspace__coordination" aria-label="智能体协同状态">
          <div class="agent-workspace__coordination-heading"><h4>当前协同</h4><span>现场 {{clock(coordination.at_seconds)}}</span></div>
          <ol class="agent-workspace__lanes">
            <li v-for="lane in coordination.lanes" :key="lane.id" :data-state="lane.state">
              <div><strong>{{lane.label}}</strong><span>{{laneLabels[lane.state]||lane.state}}</span></div><p>{{lane.detail}}</p>
            </li>
          </ol>
          <p v-if="coordination.case_tasks?.total" class="agent-workspace__case-summary">
            责任任务 {{coordination.case_tasks.completed}} / {{coordination.case_tasks.total}} 已核验；
            <template v-if="coordination.case_tasks.waiting">{{coordination.case_tasks.waiting}} 项等待火情确认，</template>
            <template v-if="coordination.case_tasks.verification_ready">{{coordination.case_tasks.verification_ready}} 项可立即提交，</template>
            <template v-if="coordination.case_tasks.overdue">{{coordination.case_tasks.overdue}} 项已超时，</template>
            {{Math.max(0,coordination.case_tasks.pending-coordination.case_tasks.verification_ready)}} 项仍需现场责任人推进。
          </p>
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
          <details v-if="['awaiting_approval','needs_review'].includes(run.status)" class="agent-workspace__constraints"><summary>修订取向与禁用出口</summary>
            <label>修订优化取向<select v-model="revisionObjective" aria-label="修订优化取向" :disabled="busy"><option value="balanced">风险与效率均衡</option><option value="low_exposure">优先降低暴露</option><option value="fast_arrival">优先尽快到场</option></select></label>
            <fieldset :disabled="busy"><legend>本次禁止使用的出口</legend><label class="agent-workspace__check"><input v-model="revisionExits" type="checkbox" value="north"/>禁止北侧出口</label><label class="agent-workspace__check"><input v-model="revisionExits" type="checkbox" value="south"/>禁止南侧出口</label></fieldset>
            <label v-if="modelAvailable" class="agent-workspace__check"><input v-model="revisionModel" type="checkbox" :disabled="busy"/>授权模型读取本次异常、知识与候选结果，核对修订建议</label>
            <p class="agent-workspace__meta">修改后点击“按当前现场重新比较”生成新版本。原目标人员不变，已受理的行动保留；本次约束不会随批准请求临时修改。</p>
          </details>
          <p v-if="run.status==='needs_review'" class="agent-workspace__notice">后续自动下令已暂停；下面保留的是原方案。请先“按当前现场重新比较”，不会取消已经受理的行动。</p>
          <p v-if="run.candidates.length" class="agent-workspace__meta">同一起点按所选路线最长预计耗时进行限时预演。预估分只反映预演时域内已形成的结果，尚未完成的核验、清点与结束项不计入，最终得分以结束复盘为准。居民北侧蓝线、南侧金线，机器人为紫线。</p>
          <p v-if="run.candidates.length===1" role="status" class="agent-workspace__meta">当前条件下没有第二个不同的可执行方案；相同动作已合并。</p>
          <div class="agent-workspace__candidates">
            <article v-for="item in run.candidates" :key="item.id" :data-selected="candidate?.id===item.id">
              <label class="agent-workspace__check"><input type="radio" :name="'candidate-'+run.id" :value="item.id" v-model="chosen" :disabled="busy" /><strong>{{item.title}}{{run.planning?.recommended_candidate_id===item.id?' · 当前推荐':''}}</strong></label>
              <p v-if="candidate?.id!==item.id" class="agent-workspace__meta">北 {{item.metrics.north}} · 南 {{item.metrics.south}} · 不可达 {{item.metrics.unreachable}} 人；选中查看预演。</p>
              <template v-if="candidate?.id===item.id">
              <p v-if="item.equivalent_rules?.length" class="agent-workspace__equivalent">{{item.equivalent_rules.join('、')}}产生完全相同的人员分配与机器人动作，系统已合并为一个可执行方案。</p>
              <section v-if="item.allocation" class="agent-workspace__decision" aria-label="出口分配依据">
                <h4>为什么这样分流</h4><p>{{item.allocation.description}}</p>
                <p v-if="item.allocation.rule==='risk_capacity'" class="agent-workspace__meta">相对路径优先方案，{{item.allocation.changed_residents}} 人调整出口。{{item.allocation.same_allocation?'当前两种规则得到相同分配，不人为制造方案差异。':''}}</p>
                <p v-if="item.baseline_metrics" class="agent-workspace__meta">相对不下达本方案、沿用原安排：{{item.forecast_seconds}} 秒后到场 {{signed(item.metrics.arrived-item.baseline_metrics.arrived)}} 人，暴露超阈值 {{signed(item.metrics.exposed-item.baseline_metrics.exposed)}} 人，累计排队 {{signed(item.metrics.queue_seconds-item.baseline_metrics.queue_seconds)}} 人秒。</p>
                <details v-if="item.allocation.bottlenecks.length">
                  <summary>查看 {{item.allocation.bottlenecks.length}} 处共享通道压力</summary>
                  <ul><li v-for="place in item.allocation.bottlenecks" :key="place.edge_id">
                    <div><strong>{{place.name}}</strong><p>本方案途经 {{place.assigned}} 人 · 其他人员当前等待 {{place.waiting}} 人<br />通行能力 {{place.flow_capacity}} 人/秒 · 现场风险 {{place.risk_score}}/100</p></div>
                    <button type="button" :disabled="busy" @click="emit('residentFocus',place.resident_id)">查看途经居民</button>
                  </li></ul>
                </details>
              </section>
              <dl><div><dt>出口分配</dt><dd>北 {{item.metrics.north}} · 南 {{item.metrics.south}}</dd></div><div><dt>不可达</dt><dd>{{item.metrics.unreachable}} 人</dd></div><div><dt>{{item.forecast_seconds}} 秒后到场</dt><dd>{{item.metrics.arrived}} 人</dd></div><div><dt>暴露超阈值</dt><dd>{{item.metrics.exposed}} 人</dd></div><div><dt>累计排队</dt><dd>{{item.metrics.queue_seconds}} 人秒</dd></div><div><dt>{{item.forecast_seconds}}秒状态预估分</dt><dd>{{item.metrics.score}} <small>（{{item.metrics.score_delta>=0?'+':''}}{{item.metrics.score_delta}}）</small></dd></div></dl>
              <p v-if="item.assist_resource?.required" class="agent-workspace__resource-summary">需护送 {{item.assist_resource.required}} 人；本场 {{item.assist_resource.capacity}} 名值守员，{{item.assist_resource.busy}} 名正在执行。{{item.assist_resource.waves ? `至少分 ${item.assist_resource.waves} 批安排，实际等待取决于在途任务。` : '当前无可用值守员，不能执行护送。'}}</p>
              <section v-if="item.release_policy" class="agent-workspace__resource" aria-label="居民放行策略">
                <h4>{{item.release_policy.mode==='building_waves'?'按楼栋分批放行':'立即组织撤离'}}</h4>
                <p>{{item.release_policy.notice}}<template v-if="item.release_policy.mode==='building_waves'">共 {{item.release_policy.waves}} 批。每栋放行前核对或接续喷水；水源失效或接续失败时，后续批次进入待复核。</template></p>
                <dl><div v-if="item.metrics.cumulative_exposure!==undefined"><dt>预演累计暴露</dt><dd>{{item.metrics.cumulative_exposure}} 模型单位</dd></div><div><dt>{{item.metrics.all_arrived?'预计全员到场时刻':'预演内末位到场时刻'}}</dt><dd>{{item.metrics.last_arrival_at!=null?clock(item.metrics.last_arrival_at):'预演内无人到场'}}</dd></div></dl>
                <p v-if="!item.metrics.all_arrived" class="agent-workspace__meta">尚未覆盖全员到场，以上时刻不代表最终疏散耗时。</p>
                <template v-if="item.schedule_assessment">
                  <p><strong>完整批次时序估算：</strong>{{item.schedule_assessment.estimated_completion_at!=null?`末批约 ${clock(item.schedule_assessment.estimated_completion_at)} 到场`:'当前条件不足，无法估计末批到场时刻'}}。</p>
                  <p class="agent-workspace__meta">{{item.schedule_assessment.notice}}</p>
                  <p v-for="risk in item.schedule_assessment.deadline_risks" :key="risk.task_id" class="agent-workspace__notice">时限风险：{{risk.title}} 截止 {{clock(risk.deadline_at)}}，按当前时序预计 {{clock(risk.estimated_ready_at)}} 才具备核验条件；尚未计入人工提交耗时。</p>
                </template>
              </section>
              <section v-if="item.robot_support" class="agent-workspace__resource" aria-label="机器人协同条件">
                <h4><AppIcon name="robot" :size="18" />{{ item.robot_support.target }}</h4>
                <dl><div><dt>预计到位</dt><dd>{{ item.robot_support.already_completed ? '已完成广播' : item.robot_support.already_arrived ? '原任务已到位' : item.robot_support.duration_seconds === null ? '暂不可达' : item.robot_support.duration_seconds + ' 秒' }}</dd></div><div v-if="!item.robot_support.already_completed"><dt>{{item.robot_support.reusing_task ? '剩余电量需求 / 当前' : '电量需求 / 当前'}}</dt><dd>{{ item.robot_support.battery_required }} / {{ item.robot_support.battery_available ?? '—' }}</dd></div></dl>
                <p>{{ item.robot_support.notice }}</p>
              </section>
              <section v-if="item.vehicle_support" class="agent-workspace__resource" aria-label="消防车压制与放行条件">
                <h4><AppIcon name="route" :size="18" />消防车压制与居民放行</h4>
                <dl><div><dt>有效停靠点</dt><dd>{{item.vehicle_support.target_name??'待重新规划'}}</dd></div><div><dt>预计开始喷水</dt><dd>{{item.vehicle_support.already_active?'正在喷水':item.vehicle_support.duration_seconds===null?'当前不可执行':item.vehicle_support.duration_seconds+' 秒后'}}</dd></div><div><dt>连续压制</dt><dd>{{item.vehicle_support.spray_duration_seconds}} 秒</dd></div></dl>
                <p>{{item.vehicle_support.notice}}</p>
                <p v-if="item.vehicle_support.water_source" class="agent-workspace__resource-summary">供水：{{item.vehicle_support.water_source.name}}<template v-if="item.vehicle_support.hose_length!==undefined"> · 水带 {{item.vehicle_support.hose_length}} 米</template>；所用水源失效后重新核对部署，不自动改用另一水源。</p>
              </section>
              <p v-else-if="item.suppression_notice" class="agent-workspace__notice">当前未提供压制后放行方案：{{item.suppression_notice}}</p>
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
          <p v-if="run.candidates.length===1" class="agent-workspace__meta">当前只有一个不同的可比较方案；等价的分流结果已合并，不重复展示。</p>
          <div class="agent-workspace__actions">
            <button v-if="run.status==='awaiting_approval'" type="button" class="agent-workspace__primary" :disabled="busy||!live||!candidate?.can_apply||!!syncError||run.approval_guard?.can_approve===false" @click="act('approve')">确认方案并执行</button>
            <button v-if="['awaiting_approval','needs_review'].includes(run.status)" type="button" :disabled="busy||drillStatus==='ended'" @click="act('replan')">按当前现场重新比较</button>
          </div>
          <p v-if="run.approval_guard?.can_approve===false && !run.approval_guard.needs_replan" class="agent-workspace__notice" role="status">{{run.approval_guard.reason}}</p>
          <p v-if="run.approval_guard?.needs_replan" class="agent-workspace__notice">{{run.approval_guard.reason}} 原预演保留用于对照，重新比较后需再次确认。</p>
          <p v-if="!live&&run.status==='awaiting_approval'" class="agent-workspace__notice">请先开始或继续演练，再确认执行。</p>
          <p v-if="!run.candidates.length">{{run.scope.completion}}</p>
        </section>
        <section v-else-if="detail==='execution'" aria-label="目标执行步骤">
          <SpeechPlayback :text="executionSpeech" :active="active&&!busy&&!voiceBusy" label="朗读当前执行摘要"/>
          <section v-if="run.resources" class="agent-workspace__ownership" aria-label="资源归属"><h4>本计划资源</h4><p class="agent-workspace__meta">已登记 {{run.resources.resident_count}} 名居民；资源归属写入数据库，刷新或重启不会重复派遣。</p><ul v-if="run.resources.items.length"><li v-for="resource in run.resources.items" :key="resource.key"><strong>{{resource.name}}</strong><span>{{({owned:'本计划占用',occupied:'其他计划占用',released:'已释放'} as Record<string,string>)[resource.state]}}<template v-if="resource.revision"> · 版本 {{resource.revision}}</template></span><button v-if="['robot','vehicle'].includes(resource.kind)||run.execution?.staff.some(staff=>resource.key==='staff:'+staff.id&&staff.resident_id)" type="button" @click="focusResource(resource.key)">定位现场</button></li></ul><p v-else class="agent-workspace__meta">当前没有独占资源；护送、机器人与车辆资源在批准时校验登记。</p></section>
          <p v-if="run.decision" class="agent-workspace__meta">执行依据：{{run.decision.title}} · 批准版本 {{run.decision.revision}} · {{clock(run.decision.approved_at)}} 确认。完整分流依据保留在“依据”中。</p>
          <button v-if="run.outcomes?.length" type="button" class="agent-workspace__disclosure" @click="openOutcomeEvidence">{{run.outcomes[0]?.result?'查看预测与实际结果差异':`查看 ${clock(run.outcomes[0]!.due_seconds)} 结果核对计划`}}<AppIcon name="arrowRight" :size="18" /></button>
          <section v-if="coordination && (coordination.issues.length || coordination.bottlenecks.length)" class="agent-workspace__attention" aria-label="需要关注的现场">
            <h4>先看这些现场</h4>
            <p v-if="(coordination.issue_count??0)>coordination.issues.length" class="agent-workspace__meta">共 {{coordination.issue_count}} 项人员风险，优先列出 {{coordination.issues.length}} 项；全部目标人员持续接受监护。</p>
            <ul><li v-for="issue in coordination.issues" :key="issue.id"><div><strong>{{issue.label}}</strong><p>{{issue.reason}}</p></div><button type="button" @click="emit('residentFocus',issue.resident_id)"><AppIcon name="target" :size="18" />定位</button></li>
            <li v-for="place in coordination.bottlenecks" :key="place.edge_id"><div><strong>{{place.name}}</strong><p>{{place.waiting}} 人等待 · 最长累计排队 {{place.max_wait_seconds}} 秒</p></div><button type="button" @click="emit('residentFocus',place.resident_id)">查看队列</button></li></ul>
          </section>
          <section v-if="coordination?.robot.included" class="agent-workspace__robot-live" aria-label="机器人实时执行">
            <div><h4><AppIcon name="robot" :size="18" />机器人协同</h4><button type="button" @click="emit('robot')">查看三维位置</button></div>
            <p>{{coordination.robot.reason||'等待机器人状态回执'}} · 电量 {{coordination.robot.battery??'—'}}%</p>
            <p class="agent-workspace__meta">到位与广播步骤已完成 {{coordination.robot.steps_completed}} / {{coordination.robot.steps_total}}</p>
          </section>
          <section v-if="coordination?.vehicle.included" class="agent-workspace__vehicle-live" aria-label="消防车实时执行">
            <div><h4><AppIcon name="route" :size="18" />消防车协同</h4><button type="button" @click="emit('vehicle')">查看车辆与处置</button></div>
            <p>{{coordination.vehicle.reason||'等待消防车状态回执'}}<template v-if="coordination.vehicle.target"> · {{coordination.vehicle.target}}</template></p>
            <p class="agent-workspace__meta">到场与喷水放行步骤已完成 {{coordination.vehicle.steps_completed}} / {{coordination.vehicle.steps_total}}</p>
          </section>
          <section v-if="coordination?.release_waves?.length" class="agent-workspace__release" aria-label="楼栋分批放行进展">
            <h4>楼栋放行进展</h4><p class="agent-workspace__meta">后一批等待前批真实到场；每批下令前核对有效喷水，火势与烟气均消退后直接满足放行条件。</p>
            <ol><li v-for="wave in coordination.release_waves" :key="wave.wave">
              <div><strong>第 {{wave.wave}} 批 · {{labels[wave.state]||wave.state}}</strong><span>到场 {{wave.arrived}} / {{wave.total}} 人</span></div><p>{{wave.reason}}</p>
              <div class="agent-workspace__building-actions"><button v-for="home in wave.buildings??[]" :key="home.id" type="button" :disabled="historical" @click="emit('buildingFocus',home.id)">定位 {{home.name}} · {{home.arrived}}/{{home.total}} 人到场</button><button v-if="wave.resident_id" type="button" @click="emit('residentFocus',wave.resident_id)">查看这批居民</button></div>
            </li></ol>
          </section>
          <p v-if="run.execution" class="agent-workspace__meta">现场同步 {{clock(run.execution.at_seconds)}} · 事件 {{run.execution.event_sequence}}。展开步骤可定位受阻人员与查看执行依据。</p>
          <p v-if="['stopped','taken_over'].includes(run.status)" class="agent-workspace__notice">自动下令已停止；下方继续显示已受理指令的实际进展。</p>
          <p v-if="!run.steps.length">方案确认后，这里显示命令进度与等待原因。</p>
          <p v-else class="agent-workspace__meta" role="status">已完成 {{ stepSummary.completed }} / {{ stepSummary.total }} 项；步骤完成依据来自实际命令回执。</p>
          <ol class="agent-workspace__steps">
            <li v-for="step in run.steps" :key="step.id">
              <div class="agent-workspace__step-heading"><strong>{{step.label}}</strong><span>{{labels[step.status]||step.status}}</span></div>
              <p v-if="dependencyLabel(step)" class="agent-workspace__meta">前置步骤：{{ dependencyLabel(step) }}</p>
              <p v-if="step.completion_rule" class="agent-workspace__meta">完成依据：{{step.completion_rule}}</p>
              <progress :value="step.progress" max="1" :aria-label="step.label+'进度'" />
              <p>{{step.reason}}</p>
              <p v-if="step.execution?.stalled" class="agent-workspace__notice">已 {{step.execution.idle_seconds}} 秒未观察到位置或命令进度变化，请定位现场检查。原指令继续保留。</p>
              <button v-if="step.resident_ids.length" type="button" @click="emit('residentFocus',step.resident_ids[0]!)">定位这组居民</button>
              <button v-else-if="step.kind==='robot.command'" type="button" @click="emit('robot')">定位机器人</button>
              <template v-if="step.execution">
                <p v-if="step.execution.total" class="agent-workspace__meta">到场 {{step.execution.arrived}} / {{step.execution.total}} · 受阻 {{step.execution.blocked}} · 正在排队 {{step.execution.queued}}</p>
                <button type="button" class="agent-workspace__disclosure" :aria-expanded="expandedStep===step.id" :aria-controls="`step-detail-${step.id}`" @click="expandedStep=expandedStep===step.id?'':step.id">{{expandedStep===step.id?'收起':'查看'}}人员与执行依据 <AppIcon name="chevron" :size="18" /></button>
                <div v-if="expandedStep===step.id" :id="`step-detail-${step.id}`" class="agent-workspace__detail">
                  <ul class="agent-workspace__people">
                    <li v-for="person in step.execution.attention" :key="person.id">
                      <div><strong>{{person.label}}</strong><button type="button" :aria-label="`定位${person.label}`" @click="emit('residentFocus',person.id)"><AppIcon name="target" :size="16" />定位</button></div>
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
          <p v-if="run.task_graph" class="agent-workspace__flow">{{run.task_graph.human_gate.label}}：{{run.task_graph.human_gate.reason}}。系统不会代签清点。</p>
          <button v-if="run.status==='awaiting_rollcall'" type="button" @click="emit('rollcall')">前往集合清点</button>
        </section>
        <section v-else aria-label="计划过程证据">
          <section v-if="run.decision" class="agent-workspace__decision" aria-label="已批准决策依据">
            <h4>{{run.decision.title}} · 版本 {{run.decision.revision}}</h4>
            <p>{{clock(run.decision.approved_at)}} 人工确认，预演起点 {{clock(run.decision.forecast_at)}}。</p>
            <p v-if="run.decision.allocation">{{run.decision.allocation.description}}</p>
            <p class="agent-workspace__meta">当时向后预演 {{run.decision.forecast_seconds}} 秒：预计到场 {{run.decision.metrics.arrived}} 人、暴露超阈值 {{run.decision.metrics.exposed}} 人、累计排队 {{run.decision.metrics.queue_seconds}} 人秒。此处保留批准时的预测，实际进展见“执行”。</p>
          </section>
          <AgentOutcomeReview v-if="run.outcomes?.length" :outcomes="run.outcomes" :elapsed="run.at_seconds" :api-base-url="apiBaseUrl" :access-token="accessToken" :run-id="run.id" @replay="at=>emit('replay',at)" @knowledge="id=>emit('knowledge',id)" />
          <p>{{run.scope.completion}}</p><ol class="agent-workspace__evidence"><li v-for="item in run.history" :key="item.id"><time>{{clock(item.at_seconds)}}</time><p>{{item.message}}</p></li></ol>
        </section>
        <div v-if="!canCreate && !historical && drillStatus!=='ended' && ['awaiting_approval','needs_review','executing','waiting','paused','awaiting_rollcall'].includes(run.status)" class="agent-workspace__stop">
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
.agent-workspace__case-tasks{display:grid;gap:10px;margin-block:20px;min-width:0}.agent-workspace__case-tasks h4,.agent-workspace__case-tasks p{margin:0}.agent-workspace__case-tasks details>button{display:grid;gap:6px;width:100%;padding:12px;text-align:start;white-space:normal;overflow-wrap:anywhere;font-size:16px}.agent-workspace__case-tasks span,.agent-workspace__case-tasks small{font-size:14px;line-height:1.6}.agent-workspace__case-tasks details>button[data-ready=true]{background:#d8e8bb;color:#173d2a;border-color:#d8e8bb}.agent-workspace__case-tasks details>button[data-overdue=true]:not([data-ready=true]){border-color:#d79b78;color:#ffd8c1}
.agent-workspace__plan-select{margin-block:var(--space-3)}
.agent-workspace__ownership{min-width:0;margin-block:var(--space-4);padding-block:var(--space-3);border-block:1px solid var(--border-default)}
.agent-workspace__ownership h4{margin:0;font-size:16px}
.agent-workspace__ownership ul{padding:0;list-style:none;margin:0}
.agent-workspace__ownership li{display:flex;flex-wrap:wrap;justify-content:space-between;gap:var(--space-2);padding-block:var(--space-2);overflow-wrap:anywhere}
.agent-workspace__ownership li span{font-size:14px;color:var(--text-secondary)}
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
.agent-workspace__equivalent{padding-block:var(--space-3);border-block:1px solid var(--border-default);color:#d9e8ca}
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
.agent-workspace__release{padding-block:var(--space-4);border-block:1px solid var(--border-default);min-width:0}.agent-workspace__release ol{list-style:none;padding:0;margin:0}.agent-workspace__release li{padding-block:var(--space-3);border-bottom:1px solid var(--border-default)}.agent-workspace__release li>div{display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px 16px}.agent-workspace__release li span,.agent-workspace__release li p{font-size:14px}.agent-workspace__release button{min-height:44px;white-space:normal}
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
.agent-workspace__coordination-heading,.agent-workspace__lanes li>div,.agent-workspace__robot-live>div,.agent-workspace__vehicle-live>div{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:var(--space-2)}
.agent-workspace h4{margin:0;font-size:16px}
.agent-workspace__coordination-heading>span,.agent-workspace__lanes li>div>span{font-size:14px;color:var(--text-secondary)}
.agent-workspace__lanes{margin:var(--space-3) 0;padding:0;list-style:none;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--space-4)}
.agent-workspace__lanes li{min-width:0;padding-top:var(--space-3);border-top:1px solid var(--border-default)}
.agent-workspace__lanes p{font-size:14px;margin:var(--space-2) 0 0;color:var(--text-secondary)}
.agent-workspace__lanes li[data-state=attention] strong,.agent-workspace__lanes li[data-state=review] strong{color:var(--status-warning)}
.agent-workspace__case-summary{padding-block:var(--space-3);border-block:1px solid var(--border-default);font-size:14px;color:var(--text-secondary)}
.agent-workspace__next{margin-top:var(--space-4)}
.agent-workspace__next button{width:100%;min-height:44px;display:flex;align-items:center;justify-content:space-between;gap:var(--space-3);white-space:normal;text-align:left}
.agent-workspace__attention{margin-block:var(--space-4)}
.agent-workspace__attention ul{list-style:none;padding:0;margin:0}
.agent-workspace__attention li{display:flex;align-items:center;gap:var(--space-3);padding-block:var(--space-3);border-bottom:1px solid var(--border-default)}
.agent-workspace__attention li>div{flex:1;min-width:0}.agent-workspace__attention li p{margin:var(--space-1) 0 0;font-size:14px;color:var(--text-secondary)}
.agent-workspace__attention button{flex-shrink:0;min-height:44px;display:flex;align-items:center;gap:var(--space-1)}
.agent-workspace__robot-live,.agent-workspace__vehicle-live{padding-block:var(--space-4);margin-bottom:var(--space-4);border-block:1px solid var(--border-default)}
.agent-workspace__robot-live h4,.agent-workspace__vehicle-live h4{display:flex;align-items:center;gap:var(--space-2)}
@media(max-width:480px){.agent-workspace__lanes{grid-template-columns:minmax(0,1fr);gap:var(--space-3)}.agent-workspace__attention li{align-items:flex-start;flex-wrap:wrap}.agent-workspace__attention li>div{flex-basis:100%}}
.agent-workspace__constraints{padding-block:12px;border-block:1px solid var(--border-default);}
.agent-workspace__case-heading{display:flex;align-items:center;justify-content:space-between;gap:8px 16px;flex-wrap:wrap;}.agent-workspace__case-heading h4{margin:0;}.agent-workspace__case-tasks summary{min-height:44px;line-height:1.7;cursor:pointer;}
.agent-workspace__case-heading button{display:inline-flex;width:auto;min-height:44px;padding:8px 12px;flex-shrink:0;}
.agent-workspace__constraints summary{min-height:44px;cursor:pointer;line-height:1.7;}
.agent-workspace__constraint-fields{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px;}
.agent-workspace__constraints fieldset{margin:12px 0;padding:12px;border:1px solid var(--border-default);border-radius:8px;}
.agent-workspace__constraints legend{font-size:14px;}.agent-workspace__constraints input:not([type=checkbox]){width:100%;box-sizing:border-box;min-height:44px;padding:10px;font:inherit;background:var(--surface-panel);color:var(--text-primary);border:1px solid var(--border-default);border-radius:6px;}
@media(max-width:540px){.agent-workspace__constraint-fields{grid-template-columns:minmax(0,1fr);}}
</style>
<style scoped>
.agent-workspace__building-actions{display:flex!important;flex-wrap:wrap;gap:8px;}
.agent-workspace__building-actions button{min-height:44px;font-size:16px;white-space:normal;overflow-wrap:anywhere;flex:1 1 160px;}
</style>
