<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { createApiClient } from '../api/client'
import type { AgentAssignment, AgentCandidate, AgentRun } from '../domain/agent'
import AppIcon from './AppIcon.vue'

const props = defineProps<{ apiBaseUrl:string;accessToken:string;drillId:string;active:boolean;historical:boolean;modelAvailable:boolean;focusId?:string }>()
const emit = defineEmits<{ preview:[people:AgentAssignment[]];focus:[id:string];robot:[];rollcall:[] }>()
const api = createApiClient(props.apiBaseUrl, () => props.accessToken)
const goal = ref('将目标居民分流疏散，重点人员安排护送'), building = ref(''), assist = ref(true), useModel = ref(false)
const robotBroadcast = ref(false)
const expandedStep = ref('')
const buildings = ref<Array<{id:string;name:string}>>([]), runs = ref<AgentRun[]>([]), drillStatus = ref('')
const loading = ref(false), busy = ref(false), error = ref(''), syncError = ref(''), chosen = ref(''), detail = ref<'plan'|'execution'|'evidence'>('plan')
let timer:ReturnType<typeof setTimeout>|undefined, generation=0, pollEpoch=0, requestId='', disposed=false
let readController:AbortController|null=null
const run = computed(() => runs.value[0])
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
const clock = (seconds:number) => `${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`
function setRun(value:AgentRun) {
  const changed = run.value?.id !== value.id
  runs.value = [value,...runs.value.filter(r => r.id!==value.id)]
  if (!value.candidates.some(p => p.id===chosen.value)) chosen.value=value.candidates[0]?.id ?? ''
  if (changed) detail.value=value.steps.length?'execution':'plan'
  if (!value.steps.some(step => step.id===expandedStep.value)) expandedStep.value=(value.steps.find(step=>['blocked','waiting','executing'].includes(step.status))??value.steps[0])?.id??''
}
async function read(initial=false, reconcile=false) {
  if (!props.active || props.historical || disposed || (busy.value && !reconcile)) return
  const version=generation, scope=props.drillId
  readController?.abort(); const controller=new AbortController();readController=controller
  if (initial) loading.value=true
  try {
    const value=await api.get<{buildings:Array<{id:string;name:string}>;runs:AgentRun[];drill_status:string}>(`/drills/${scope}/agent/runs`,{signal:controller.signal})
    if (version!==generation || scope!==props.drillId || disposed) return
    buildings.value=value.buildings;drillStatus.value=value.drill_status;syncError.value=''
    if(value.runs[0])setRun(value.runs[0])
    runs.value=value.runs
    if (run.value?.candidates.length && !run.value.candidates.some(p=>p.id===chosen.value)) chosen.value=run.value.candidates[0]!.id
  } catch(cause) { if (version===generation && !controller.signal.aborted) syncError.value=cause instanceof Error?cause.message:'目标计划读取失败，请重试。' }
  finally { if(version===generation)loading.value=false;if(readController===controller)readController=null }
}
async function poll(epoch=pollEpoch) {
  await read()
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
async function act(action:'approve'|'stop'|'replan') {
  if(!run.value||busy.value||props.historical)return
  generation++;readController?.abort();const current=run.value,version=generation;busy.value=true;error.value=''
  try{
    const value=await api.post<AgentRun>(`/drills/${props.drillId}/agent/runs/${current.id}/actions`,{action,revision:current.revision,candidate_id:action==='approve'?candidate.value?.id:null})
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
      <div class="agent-workspace__intro"><h3>分流、护送与机器人协同</h3><p>选择楼栋与行动范围，比较方案后确认执行。居民先行撤离，机器人独立前往楼门，到位后广播；最后由参演者核验清点。</p></div>
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
        <p v-if="run.scope.robot_broadcast" class="agent-workspace__flow">居民分流与护送并行推进；机器人到位后广播，两条支线完成后核验清点。</p>
        <dl class="agent-workspace__counts"><div><dt>到集合点</dt><dd>{{run.summary.arrived}} / {{run.summary.total}}</dd></div><div><dt>已清点</dt><dd>{{run.summary.counted}}</dd></div><div><dt>已会合护送</dt><dd>{{run.summary.assisted}}</dd></div><div><dt>暴露超阈值</dt><dd>{{run.summary.exposed}}</dd></div></dl>
        <nav class="agent-workspace__tabs" aria-label="目标计划视图"><button v-for="tab in (['plan','execution','evidence'] as const)" :key="tab" type="button" :aria-pressed="detail===tab" @click="detail=tab">{{ ({plan:'方案',execution:'执行',evidence:'依据'})[tab] }}</button></nav>
        <section v-if="detail==='plan'" aria-label="候选分流方案">
          <p v-if="run.candidates.length" class="agent-workspace__meta">同一起点向后预演 30 秒。居民北侧蓝线、南侧金线，最多显示 48 条代表路线；机器人为紫线。</p>
          <div class="agent-workspace__candidates">
            <article v-for="item in run.candidates" :key="item.id" :data-selected="candidate?.id===item.id">
              <label class="agent-workspace__check"><input type="radio" :name="'candidate-'+run.id" :value="item.id" v-model="chosen" :disabled="busy" /><strong>{{item.title}}</strong></label>
              <p v-if="candidate?.id!==item.id" class="agent-workspace__meta">北 {{item.metrics.north}} · 南 {{item.metrics.south}} · 不可达 {{item.metrics.unreachable}} 人；选中查看预演。</p>
              <template v-if="candidate?.id===item.id">
              <dl><div><dt>出口分配</dt><dd>北 {{item.metrics.north}} · 南 {{item.metrics.south}}</dd></div><div><dt>不可达</dt><dd>{{item.metrics.unreachable}} 人</dd></div><div><dt>30 秒后到场</dt><dd>{{item.metrics.arrived}} 人</dd></div><div><dt>暴露超阈值</dt><dd>{{item.metrics.exposed}} 人</dd></div><div><dt>累计排队</dt><dd>{{item.metrics.queue_seconds}} 人秒</dd></div><div><dt>全场预测分</dt><dd>{{item.metrics.score}} <small>（{{item.metrics.score_delta>=0?'+':''}}{{item.metrics.score_delta}}）</small></dd></div></dl>
              <p v-if="item.assist_resource?.required" class="agent-workspace__resource-summary">需护送 {{item.assist_resource.required}} 人；本场 {{item.assist_resource.capacity}} 名值守员，{{item.assist_resource.busy}} 名正在执行。{{item.assist_resource.waves ? `至少分 ${item.assist_resource.waves} 批安排，实际等待取决于在途任务。` : '当前无可用值守员，不能执行护送。'}}</p>
              <section v-if="item.robot_support" class="agent-workspace__resource" aria-label="机器人协同条件">
                <h4><AppIcon name="robot" :size="18" />{{ item.robot_support.target }}</h4>
                <dl><div><dt>预计到位</dt><dd>{{ item.robot_support.already_completed ? '已完成广播' : item.robot_support.duration_seconds === null ? '暂不可达' : item.robot_support.duration_seconds + ' 秒' }}</dd></div><div v-if="!item.robot_support.already_completed"><dt>电量需求 / 当前</dt><dd>{{ item.robot_support.battery_required }} / {{ item.robot_support.battery_available ?? '—' }}</dd></div></dl>
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
            <button v-if="run.status==='awaiting_approval'" type="button" class="agent-workspace__primary" :disabled="busy||!live||!candidate?.can_apply||!!syncError" @click="act('approve')">确认方案并执行</button>
            <button v-if="['awaiting_approval','needs_review'].includes(run.status)" type="button" :disabled="busy||drillStatus==='ended'" @click="act('replan')">按当前现场重新比较</button>
          </div>
          <p v-if="!live&&run.status==='awaiting_approval'" class="agent-workspace__notice">请先开始或继续演练，再确认执行。</p>
          <p v-if="!run.candidates.length">{{run.scope.completion}}</p>
        </section>
        <section v-else-if="detail==='execution'" aria-label="目标执行步骤">
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
        <section v-else aria-label="计划过程证据"><p>{{run.scope.completion}}</p><ol class="agent-workspace__evidence"><li v-for="item in run.history" :key="item.id"><time>{{clock(item.at_seconds)}}</time><p>{{item.message}}</p></li></ol></section>
        <div v-if="!canCreate" class="agent-workspace__stop"><button type="button" :disabled="busy" @click="act('stop')">{{run.steps.length?'停止后续自动下令':'取消未执行方案'}}</button><p>已受理的动作仍继续。暂停现场请使用顶部“暂停演练”；人工改派后，本计划会让出控制。</p></div>
      </article>
    </template>
  </section>
</template>

<style scoped>
.agent-workspace{min-width:0;font-size:16px;line-height:1.65;color:#e9f1e8}
.agent-workspace h3{font-size:20px;margin:0 0 8px}.agent-workspace p{margin:8px 0 12px;overflow-wrap:anywhere}
.agent-workspace__intro{padding-bottom:16px;border-bottom:1px solid #335347;margin-bottom:18px}
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
</style>
