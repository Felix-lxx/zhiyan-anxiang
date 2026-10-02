<script setup lang="ts">
import { createApiClient } from '../api/client'
import { sendCommand } from '../api/commands'

import { computed, nextTick, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'

type Point = { x: number; y: number; height?: number }
type Person = Point & { id: string; label: string; floor?: number; current_floor?: number; status: string; indoor_stage?: string; counted?: boolean; last_location?: string; search_responsible?: string; behavior?: string; vulnerable: boolean; route_reachable?: boolean; route_points?: Point[]; remaining_seconds?: number; queue_seconds?: number }
interface State { id: string; status: string; elapsed_seconds: number; branch?: { source_name: string } | null; simulation: { residents: Person[] }; events: Array<{ sequence: number; event_type: string; message: string; elapsed_seconds: number }> }
interface ResidentPreview {
  residents: Person[]; can_apply: boolean; notice: string; at_seconds: number; expected_sequence: number
  planned_duration_seconds?: number | null
  impact?: { congested_before: number; congested_after: number; smoke_exposed_before: number; smoke_exposed_after: number; forecast_horizon_seconds: number }
  score_impact?: { before: number; after: number; delta: number; note: string }
}
const props = defineProps<{ drill: State; apiBaseUrl: string; accessToken: string; replay: boolean }>()
const api = createApiClient(props.apiBaseUrl, () => props.accessToken)
const emit = defineEmits<{ updated: [value: unknown]; forked: [value: unknown]; select: [ids: string[]]; preview: [people: Person[]]; focus: [id: string]; compare: [] }>()
const tab = ref<'command' | 'rollcall' | 'branch'>('command'), selected = ref<string[]>([]), exit = ref<'north' | 'south'>('north')
const pending = ref(false), error = ref(''), notice = ref(''), searchId = ref(''), responsible = ref('物业搜索员甲')
const draft = ref<ResidentPreview | null>(null)
const action = ref<'evacuate' | 'priority_assist'>('evacuate')
const confirmPanel = ref<HTMLElement|null>(null)
const people = computed(() => props.drill.simulation.residents)
const floors = computed(() => [...new Set(people.value.map(p => p.floor ?? 1))].sort((a,b) => b-a))
const arrived = computed(() => people.value.filter(p => p.status === 'evacuated' && !p.counted))
const missing = computed(() => people.value.filter(p => p.status !== 'evacuated'))
const decisions = computed(() => props.drill.events.filter(e => ['inject.channel_blocked','resident.command'].includes(e.event_type)))
const canAct = computed(() => !pending.value && !props.replay && props.drill.status === 'running')
let generation = 0
async function request(path: string, body: unknown): Promise<any> {
  return api.post(`/drills/${props.drill.id}${path}`,body)
}
function selectIds(ids: string[]) { generation++; selected.value = ids; draft.value = null; emit('preview', []); emit('select', ids) }
function selectFloor(floor: number) { selectIds(people.value.filter(p => p.status !== 'evacuated' && p.indoor_stage !== 'outdoor' && Math.max(1,Math.ceil(p.current_floor ?? p.floor ?? 1)) === floor).map(p => p.id)) }
async function previewCommand(command: { residentIds: string[]; exit: 'north' | 'south'; action: 'evacuate' | 'priority_assist' }) {
  selectIds(command.residentIds); exit.value = command.exit; action.value = command.action; tab.value = 'command'
  if (!selected.value.length) return
  const current = generation; pending.value = true; error.value = ''; notice.value = ''
  try { const value = await request('/residents/preview', { resident_ids: selected.value, exit: exit.value, action: action.value }); if (current === generation) { draft.value = value; emit('preview', value.residents); await nextTick(); confirmPanel.value?.scrollIntoView({block:'nearest',behavior:'instant'}) } }
  catch (cause) { error.value = String(cause instanceof Error ? cause.message : cause) }
  finally { pending.value = false }
}
async function run(path: string, body: unknown, message: string, expectedSequence?: number) {
  pending.value = true; error.value = ''; notice.value = ''
  try { emit('updated', await sendCommand(api, props.drill.id, path, body, 'POST', expectedSequence)); notice.value = message; draft.value = null; emit('preview', []) }
  catch (cause) {
    const message = String(cause instanceof Error ? cause.message : cause)
    error.value = message
    if (path === '/residents' && expectedSequence !== undefined && message.includes('重新预览')) {
      const command = body as { resident_ids: string[]; exit: 'north' | 'south'; action: 'evacuate' | 'priority_assist' }
      await previewCommand({ residentIds: command.resident_ids, exit: command.exit, action: command.action })
      notice.value = '现场状态已变化，已按最新人员、道路和烟气状态重新生成预览，请再次确认。'
    }
  }
  finally { pending.value = false }
}
async function fork(at: number, sequence?: number) {
  pending.value = true; error.value = ''
  try { emit('forked', await request('/branches', { at_seconds: at, before_sequence: sequence, name: `另一种选择 · ${at}秒` })) }
  catch (cause) { error.value = String(cause instanceof Error ? cause.message : cause) }
  finally { pending.value = false }
}
watch(() => props.drill.id, () => { selectIds([]); error.value = ''; notice.value = '' })
watch(() => props.replay, () => selectIds([]))
function openTab(value: 'command' | 'rollcall' | 'branch') { tab.value = value }
defineExpose({ previewCommand, selectIds, openTab })
</script>

<template>
  <section class="spatial-lab" aria-label="连续空间训练">
    <nav aria-label="训练操作"><button :aria-pressed="tab==='command'" @click="tab='command'"><AppIcon name="route"/>指挥</button><button :aria-pressed="tab==='rollcall'" @click="tab='rollcall'"><AppIcon name="users"/>清点</button><button :aria-pressed="tab==='branch'" @click="tab='branch'"><AppIcon name="split"/>重做</button></nav>
    <p v-if="error" class="lab-error" role="alert">{{ error }}</p><p v-if="notice" class="lab-notice" role="status">{{ notice }}</p><p v-if="pending" role="status">正在校验场次与路线…</p>
    <template v-if="tab==='command'">
      <h2>选人 → 预览 → 确认</h2><p>点选一层，或切到三维「居民」工具拖动框选。点击北／南出口也能预览路线。</p>
      <div class="floor-select"><button v-for="floor in floors" :key="floor" :disabled="pending" @click="selectFloor(floor)">{{ floor }}F</button></div>
      <div class="selection-count"><strong>已选 {{ selected.length }} 人</strong><button @click="selectIds([])">清除选择</button></div>
      <button :disabled="!canAct" @click="selectIds(selected); notice='已切换框选：在三维画面中按住并拖动，再点击出口预览路线。'">三维框选</button>
      <label>逐人选择<select aria-label="逐人选择" @change="selectIds([( $event.target as HTMLSelectElement).value]); emit('focus', ($event.target as HTMLSelectElement).value)"><option value="">请选择</option><option v-for="p in people.filter(p=>p.status!=='evacuated')" :key="p.id" :value="p.id">{{ p.label }} · {{ p.last_location }}</option></select></label>
      <div class="exit-actions"><button :disabled="!selected.length || pending || replay" @click="previewCommand({residentIds:selected,exit:'north',action:'evacuate'})">预览北侧路线</button><button :disabled="!selected.length || pending || replay" @click="previewCommand({residentIds:selected,exit:'south',action:'evacuate'})">预览南侧路线</button></div>
      <button :disabled="!selected.length || pending || replay || selected.some(id=>!people.find(p=>p.id===id)?.vulnerable)" @click="previewCommand({residentIds:selected,exit,action:'priority_assist'})">为所选重点居民预览护送</button>
      <section v-if="draft" ref="confirmPanel" class="route-confirm" aria-label="路线预览确认">
        <h3>{{ exit==='north'?'北':'南' }}侧集合点 · {{ draft.residents.length }} 人</h3>
        <p>虚线为拟执行路线，尚未下令。{{ draft.can_apply ? '所选人员可达。' : '含不可达或已到达人员，请重新选择。' }}</p>
        <dl class="route-impact">
          <div><dt>预计最长用时</dt><dd>{{ draft.planned_duration_seconds ?? '—' }}<small v-if="draft.planned_duration_seconds"> 秒</small></dd></div>
          <div v-if="draft.impact"><dt>拥堵人数</dt><dd>{{ draft.impact.congested_before }} → {{ draft.impact.congested_after }}</dd></div>
          <div v-if="draft.impact"><dt>烟气暴露</dt><dd>{{ draft.impact.smoke_exposed_before }} → {{ draft.impact.smoke_exposed_after }}</dd></div>
          <div v-if="draft.score_impact"><dt>预计得分变化</dt><dd>{{ draft.score_impact.delta > 0 ? '+' : '' }}{{ draft.score_impact.delta }}</dd></div>
        </dl>
        <ol><li v-for="p in draft.residents.slice(0,6)" :key="p.id">{{ p.label }}：{{ p.route_reachable ? `行走估计 ${p.remaining_seconds} 秒` : '不可达' }}</li></ol>
        <p class="route-confirm__note">{{ draft.score_impact?.note ?? draft.notice }}</p>
        <button class="confirm-route" :disabled="!canAct || !draft.can_apply" @click="run('/residents',{resident_ids:selected,exit,action},'指令已生效。观察选中人员的位置、队列和去向；历史轨迹不会被清零。',draft.expected_sequence)">确认下达{{ action==='priority_assist'?'护送':'撤离' }}指令</button>
      </section>
      <details><summary>逐人跟随与队列</summary><ul class="resident-checklist"><li v-for="p in people" :key="p.id"><button @click="emit('focus',p.id)">{{ p.label }}</button><span>{{ p.last_location }}<small>{{ p.behavior }} · 累计排队 {{ Math.round(p.queue_seconds??0) }} 秒</small></span></li></ul></details>
    </template>
    <template v-else-if="tab==='rollcall'">
      <h2>到集合点，才算到场</h2><p>到出口仍要走完集合通道。清点不会把失联人员直接变成已到达。</p>
      <div class="rollcall-summary"><span>已核验 <b>{{ people.filter(p=>p.counted).length }}</b></span><span>待清点 <b>{{ arrived.length }}</b></span><span>未到达 <b>{{ missing.length }}</b></span></div>
      <ul class="resident-checklist"><li v-for="p in arrived" :key="p.id"><span>{{ p.label }}<small>{{ p.last_location }}</small></span><button :disabled="!canAct" @click="run('/participant-actions',{role:'居民代表',action:'resident_counted',message:`集合点逐人核验：${p.label}`,resident_ids:[p.id]},`${p.label}清点已记录。`)">核验到场</button></li></ul><p v-if="!arrived.length">暂无待清点居民。让居民到达集合点后再核验。</p>
      <h3>未到名单与搜索责任</h3><label>选择寻找对象<select v-model="searchId"><option value="">请选择未到居民</option><option v-for="p in missing" :key="p.id" :value="p.id">{{ p.label }} · {{ p.last_location }}</option></select></label><label>搜索责任人<input v-model="responsible" maxlength="40" placeholder="输入责任人姓名" /></label><button :disabled="!canAct || !searchId || responsible.trim().length<2" @click="run('/searches',{resident_id:searchId,responsible:responsible.trim()},'已派出搜索员；沿实际通道到达并会合后，居民才恢复撤离。')">派出搜索员</button>
      <ul class="resident-checklist"><li v-for="p in missing" :key="p.id"><button @click="emit('focus',p.id)">{{ p.label }}</button><span>{{ p.last_location }}<small>{{ p.search_responsible ? '责任人：'+p.search_responsible : '尚未指派搜索' }} · {{ p.behavior }}</small></span></li></ul>
    </template>
    <template v-else>
      <h2>从决定前重新选择</h2><p>复制当时的人员、位置、暴露、队列与任务。原训练保留，之后的封路与指令不带入新分支。</p><p v-if="drill.branch">当前是「{{ drill.branch.source_name }}」的分支。点击顶部继续训练后，可选择不同路线。</p>
      <button :disabled="pending" @click="fork(drill.elapsed_seconds)">从当前{{ replay?'回放':'' }}时刻创建分支</button><button v-if="drill.branch" :disabled="pending" @click="emit('compare')">对照原训练的同一时刻</button>
      <ol class="branch-decisions"><li v-for="e in decisions" :key="e.sequence"><span>{{ e.elapsed_seconds }} 秒 · {{ e.message }}</span><button :disabled="pending" @click="fork(e.elapsed_seconds,e.sequence)">从这次决定前重做</button></li></ol><p v-if="!decisions.length">先下达路线或封锁道路，就会在这里出现可重做的决定。</p>
    </template>
    <footer>示例户型 · 连续通道规则模型<br/>用于训练决策与协作，不用于证明现实疏散安全。</footer>
  </section>
</template>

<style scoped>
.spatial-lab{padding:20px 0;border-top:1px solid #d7dfd9;color:#183b33}.spatial-lab nav{display:grid;grid-template-columns:repeat(3,1fr);gap:4px;background:#e3eae4;border-radius:10px;padding:4px;margin-bottom:20px}.spatial-lab nav button{display:flex;align-items:center;justify-content:center;gap:6px;margin:0;border:0;background:none;padding:10px 6px}.spatial-lab nav button[aria-pressed=true]{background:#fff;box-shadow:0 1px 4px #183b3320}.spatial-lab h2{font-size:19px;line-height:1.4}.spatial-lab h3{font-size:16px;margin:18px 0 8px}.spatial-lab p,.spatial-lab label{font-size:14px;line-height:1.65}.spatial-lab label{display:grid;gap:5px;margin:12px 0}.spatial-lab select,.spatial-lab input{width:100%;min-width:0;max-width:100%;padding:10px;font-size:14px;border:1px solid #bccdc5;border-radius:7px;background:#fff}.spatial-lab button{min-height:44px;max-width:100%;white-space:normal;line-height:1.4;border-radius:7px;cursor:pointer}.floor-select{display:flex;flex-wrap:wrap;gap:6px}.floor-select button{min-width:44px;width:auto;margin:0}.selection-count{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:12px}.selection-count button{width:auto;font-size:14px;border:0}.exit-actions{display:grid;grid-template-columns:1fr 1fr;gap:8px}.route-confirm{border:1px solid #bdd0c4;border-radius:8px;background:#e6f0e8;padding:16px;margin:14px 0}.route-impact{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:12px 0}.route-impact>div{background:#f6f9f5;border-radius:6px;padding:10px}.route-impact dt{color:#587467;font-size:13px}.route-impact dd{margin:3px 0 0;font-size:17px;font-weight:700;font-variant-numeric:tabular-nums}.route-confirm .confirm-route{background:#195647;color:white;border-color:#195647;margin-top:12px}.route-confirm ol{padding-left:20px;font-size:14px}.route-confirm__note{color:#4d6b5f}.route-confirm small{font-size:13px}.resident-checklist{padding:0;list-style:none;max-height:260px;overflow:auto}.resident-checklist li{display:flex;align-items:center;gap:8px;border-bottom:1px solid #dae2dc;padding:9px 0;font-size:14px}.resident-checklist button{flex-shrink:0;width:auto;margin:0;font-size:14px;padding:6px}.resident-checklist span{min-width:0;overflow-wrap:anywhere}.resident-checklist small{display:block;color:#587467;font-size:13px}.rollcall-summary{display:flex;flex-wrap:wrap;gap:12px;font-size:14px}.rollcall-summary b{display:block;font-size:22px}.branch-decisions{padding-left:18px;font-size:14px}.branch-decisions li{margin-top:16px}.spatial-lab .lab-error{background:#f9e4dd;padding:10px;color:#912c1e}.spatial-lab .lab-notice{background:#dfede2;padding:10px}.spatial-lab footer{margin-top:18px;font-size:13px;color:#61796d;line-height:1.6}.spatial-lab details{margin-top:16px}.spatial-lab summary{cursor:pointer;font-size:14px}
</style>

<style scoped>
.spatial-lab nav button{color:#234a3b}.spatial-lab nav button[aria-pressed=true]{color:#123e31}.spatial-lab nav svg{color:currentColor}.spatial-lab button:focus-visible{outline:3px solid #9c742c;outline-offset:2px}
</style>
