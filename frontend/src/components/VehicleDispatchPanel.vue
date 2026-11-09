<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Vehicle, SpatialIntent, TransferCandidate } from '../domain/drill'
import AppIcon from './AppIcon.vue'
const props = defineProps<{ vehicles: Vehicle[]; nodes: Array<{ id: string; name: string; is_exit?: boolean; x?: number; y?: number }>; candidates?: TransferCandidate[]; running: boolean; busy: boolean; selectedId?: string; drillStatus?: string }>()
const emit = defineEmits<{ preview: [intent: SpatialIntent]; command: [id: string, command: 'cancel' | 'replan' | 'stop_action']; focus: [vehicle: Vehicle] }>()
const chosen = ref(''), target = ref(''), patient = ref(''), waterSource = ref('')
const activeView = ref<'dispatch' | 'service'>('dispatch')
watch(chosen, () => { target.value = ''; patient.value = ''; waterSource.value = '' })
watch(() => props.selectedId, id => { if (id) chosen.value = id }, { immediate: true })
watch(() => props.vehicles.map(v => v.id).join(','), () => { if (!props.vehicles.some(v => v.id === chosen.value)) chosen.value = props.vehicles[0]?.id ?? '' }, { immediate: true })
watch(() => props.nodes, nodes => { if (!nodes.some(n => n.id === target.value)) target.value = '' })
const vehicle = computed(() => props.vehicles.find(v => v.id === chosen.value))
const waterSources = computed(() => vehicle.value?.service_options?.spray?.water_sources ?? [])
const selectedWater = computed(() => waterSources.value.find(item => item.id === waterSource.value))
watch(() => vehicle.value?.state, (state, previous) => {
  if (state === 'arrived' && previous && previous !== 'arrived') activeView.value = 'service'
})
watch(() => vehicle.value?.service?.action, action => {
  if (action) activeView.value = 'service'
}, {immediate:true})
watch(waterSources, sources => {
  if (waterSource.value && !sources.some(item => item.id === waterSource.value)) waterSource.value = ''
})
const active = computed(() => vehicle.value && ['moving', 'blocked', 'yielding'].includes(vehicle.value.state))
const disabled = computed(() => !props.running || props.busy)
const destinations = computed(() => props.nodes.filter(n => !vehicle.value?.passenger || n.is_exit && n.id !== vehicle.value.passenger.pickup_node_id))
watch(destinations, nodes => { if (!nodes.some(n => n.id === target.value)) target.value = '' })
watch(() => props.candidates, list => { if (!list?.some(p => p.id === patient.value && p.eligible)) patient.value = '' })
const labels = { idle: '待命', moving: '前往目标', blocked: '通道受阻', arrived: '已到场', yielding: '等待人员通过' }
function atCurrentNode(node: { x?: number; y?: number }) {
  return vehicle.value && node.x !== undefined && node.y !== undefined && Math.hypot(node.x - vehicle.value.x, node.y - vehicle.value.y) < .03
}
function preview(command: 'spray' | 'load' | 'handover') {
  if (vehicle.value) emit('preview', { kind: 'vehicle', vehicleId: vehicle.value.id, command,
    residentId: command === 'load' ? patient.value : undefined,
    waterSourceId: command === 'spray' ? waterSource.value || undefined : undefined })
}
</script>

<template>
  <section v-if="vehicles.length" class="vehicle-dispatch" :data-view="activeView" aria-label="应急车辆调度">
    <header><div><h3 id="vehicle-dispatch-heading" tabindex="-1">车辆调度与到场处置</h3><p>{{activeView==='dispatch'?'选择车辆与另一处道路节点 → 预览路线 → 确认执行。预览不会让车辆出发。':vehicle?.kind==='ambulance'?'车辆停稳后，选择已清点人员预览接运；到另一出口后办理移交。':'车辆停稳后选择水源，预览供水连接并确认；失效水源不会自动替换。'}}</p></div><AppIcon name="route" :size="22" /></header>
    <p v-if="!running" class="vehicle-dispatch__hint" role="status">{{ drillStatus === 'ended' ? '本场已经结束，车辆保持历史位置。请点击顶部的“新开一轮”。' : drillStatus === 'ready' ? '当前尚未开始。请先点击顶部的“开始推演”，再调度车辆。' : '当前处于暂停或历史查看状态。请先返回实时现场并继续演练。' }}</p>
    <div class="vehicle-dispatch__views" role="group" aria-label="车辆操作视图">
      <button type="button" :aria-pressed="activeView==='dispatch'" @click="activeView='dispatch'">到场调度</button>
      <button type="button" :aria-pressed="activeView==='service'" @click="activeView='service'">{{vehicle?.kind==='ambulance'?'接运与移交':'供水与喷水'}}</button>
    </div>
    <div class="vehicle-dispatch__fields">
      <div><label for="dispatch-vehicle">调度车辆</label><select id="dispatch-vehicle" v-model="chosen"><option v-for="item in vehicles" :key="item.id" :value="item.id">{{ item.name }} · {{ labels[item.state] }}</option></select></div>
      <div v-show="activeView==='dispatch'"><label for="dispatch-target">{{ vehicle?.passenger ? '转运接应出口' : '到场位置' }}</label><select id="dispatch-target" v-model="target" :disabled="Boolean(active || vehicle?.service) || disabled"><option value="" disabled>选择另一处道路节点</option><option v-for="node in destinations" :key="node.id" :value="node.id" :disabled="Boolean(atCurrentNode(node))">{{ node.name }}{{ atCurrentNode(node) ? '（车辆当前位置）' : '' }}</option></select></div>
    </div>
    <template v-if="vehicle">
      <div v-show="activeView==='dispatch'" class="vehicle-dispatch__status" role="status"><strong>{{ labels[vehicle.state] }}<span v-if="vehicle.remaining_seconds !== null"> · 剩余 {{ vehicle.remaining_seconds }} 秒</span></strong><p>{{ vehicle.reason }}</p><small>通行宽度需求 {{ vehicle.minimum_width }} 米 · {{ running ? '与演练时钟同步' : '当前时刻已冻结' }}</small></div>
      <progress v-if="activeView==='dispatch'&&(active || vehicle.state === 'arrived')" :value="vehicle.progress" max="1" aria-label="车辆到场进度" />
      <div v-show="activeView==='dispatch'" class="vehicle-dispatch__actions">
        <button type="button" @click="emit('focus', vehicle)"><AppIcon name="target" :size="16" />定位车辆</button>
        <template v-if="activeView==='dispatch'">
          <template v-if="active"><button type="button" :disabled="disabled" @click="emit('command', vehicle.id, 'replan')">重算路线</button><button v-if="!vehicle.passenger" type="button" :disabled="disabled" @click="emit('command', vehicle.id, 'cancel')">取消行程</button></template>
          <button v-else type="button" class="vehicle-dispatch__primary" :disabled="disabled || !target || Boolean(vehicle.service)" @click="emit('preview', { kind: 'vehicle', vehicleId: vehicle.id, targetNodeId: target })"><AppIcon name="route" :size="16" />预览{{ vehicle.passenger ? '转运' : '到场' }}路线</button>
        </template>
      </div>
      <section v-show="activeView==='service'" class="vehicle-dispatch__service" aria-label="到场处置">
        <div class="vehicle-dispatch__service-heading"><h4>{{ vehicle.kind === 'firetruck' ? '水源连接与喷水' : '人员接运与移交' }}</h4><button type="button" @click="emit('focus',vehicle)">定位车辆</button></div>
        <p v-if="!vehicle.service" class="vehicle-dispatch__hint" role="status">{{labels[vehicle.state]}} · {{vehicle.reason}}</p>
        <div v-if="vehicle.service" class="vehicle-dispatch__status" role="status">
          <strong>{{ vehicle.service.label }} · {{ Math.round(vehicle.service.progress * 100) }}%</strong>
          <p v-if="vehicle.service.resident_label">接运人员：{{ vehicle.service.resident_label }}</p>
          <p v-if="vehicle.service.water_source">供水：{{ vehicle.service.water_source.name }}</p>
          <p v-if="vehicle.service.hose_length !== undefined">已铺设水带 {{vehicle.service.hose_length}} 米 · 与场内连接路径同步</p>
          <p>{{ vehicle.service.reason }} · 剩余 {{ vehicle.service.remaining_seconds }} 秒</p>
          <progress :value="vehicle.service.progress" max="1" aria-label="到场处置进度" />
          <div v-if="vehicle.service.action === 'spray'" class="vehicle-dispatch__actions"><button type="button" :disabled="disabled" @click="emit('command', vehicle.id, 'stop_action')">停止喷水</button></div>
        </div>
        <template v-else-if="vehicle.kind === 'firetruck'">
          <label v-if="waterSources.length" class="vehicle-dispatch__water" for="dispatch-water-source">供水水源
            <select id="dispatch-water-source" v-model="waterSource" :disabled="disabled">
              <option value="">自动选择可用的最短连接</option>
              <option v-for="source in waterSources" :key="source.id" :value="source.id" :disabled="!source.can_connect">{{source.name}} · {{source.state==='failed'?'失效':source.can_connect?'水带 '+source.hose_length+' 米':'当前无法接入'}}</option>
            </select>
          </label>
          <p v-if="selectedWater" class="vehicle-dispatch__hint" role="status">{{selectedWater.name}}：{{selectedWater.notice}}</p>
          <ul v-if="waterSources.some(source=>!source.can_connect)" class="vehicle-dispatch__water-status" aria-label="水源限制">
            <li v-for="source in waterSources.filter(item=>!item.can_connect)" :key="source.id"><strong>{{source.name}}</strong><span>{{source.notice}}</span></li>
          </ul>
          <p>{{ vehicle.service_options?.spray?.notice ?? '到场处置需要连续空间场次及可用水源。' }}</p>
          <div class="vehicle-dispatch__actions"><button type="button" :disabled="disabled || !vehicle.service_options?.spray?.can_apply || Boolean(selectedWater&&!selectedWater.can_connect)" @click="preview('spray')">预览喷水处置</button></div>
        </template>
        <template v-else-if="vehicle.passenger">
          <p><strong>{{ vehicle.passenger.label }}</strong> 已上车。请驶往另一出口完成医疗移交；车内有人时保留接运责任。</p>
          <p class="vehicle-dispatch__hint">{{ vehicle.service_options?.handover?.notice }}</p>
          <div class="vehicle-dispatch__actions"><button type="button" :disabled="disabled || !vehicle.service_options?.handover?.can_apply" @click="preview('handover')">预览医疗移交</button></div>
        </template>
        <template v-else>
          <p>先在集合点清点重点人员或烟气暴露人员，将救护车停在同侧出口，再安排接运。</p>
          <label v-if="candidates?.length" class="vehicle-dispatch__patient">接运人员<select v-model="patient" :disabled="disabled || active"><option value="" disabled>选择已清点的人员</option><option v-for="person in candidates" :key="person.id" :value="person.id" :disabled="!person.eligible">{{ person.label }} · {{ person.exit === 'north' ? '北侧' : '南侧' }} · {{ person.reason }}</option></select></label>
          <p v-else class="vehicle-dispatch__hint">暂无符合条件的到场人员。先完成疏散与集合清点。</p>
          <div class="vehicle-dispatch__actions"><button type="button" :disabled="disabled || active || !patient" @click="preview('load')">预览接运路径</button></div>
        </template>
      </section>
      <details v-if="vehicle.rescue_actions?.length" class="vehicle-dispatch__history">
        <summary>处置记录 · {{ vehicle.rescue_action_count ?? vehicle.rescue_actions.length }} 项</summary>
        <ol><li v-for="item in vehicle.rescue_actions.slice(-6).reverse()" :key="item.action_id"><strong>{{ item.label }} · {{ item.status === 'completed' ? '已完成' : item.status === 'cancelled' ? '已停止' : '执行中' }}</strong><p>{{ item.resident_label || item.water_source?.name }} · {{ item.reason }}</p></li></ol>
        <small>此处展示最近 6 项；完整操作时间与结果保存在事件证据中。</small>
      </details>
    </template>
  </section>
</template>

<style scoped>
.vehicle-dispatch__views { display:flex; gap:8px; margin-block:20px 12px; flex-wrap:wrap; }
.vehicle-dispatch__views button { flex:1 1 140px; min-height:44px; padding:10px 12px; font:inherit; font-size:16px; color:var(--text-primary); background:var(--surface-raised); border:1px solid var(--border-default); border-radius:var(--radius-sm,6px); cursor:pointer; }
.vehicle-dispatch__views button[aria-pressed=true] { background:var(--action-primary); border-color:var(--action-primary); }
.vehicle-dispatch[data-view=service] .vehicle-dispatch__service { margin-top:16px; padding-top:0; border-top:0; }
.vehicle-dispatch__service-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; }
.vehicle-dispatch__service-heading h4 { margin:0; }
.vehicle-dispatch__service-heading button { min-height:44px; padding:8px 12px; font:inherit; font-size:16px; background:var(--surface-raised); color:var(--text-primary); border:1px solid var(--border-default); border-radius:var(--radius-sm,6px); cursor:pointer; }
.vehicle-dispatch__water { margin-block:16px 12px; }
.vehicle-dispatch__water-status { list-style:none; padding:0; margin:12px 0 16px; font-size:14px; line-height:1.6; }
.vehicle-dispatch__water-status li { display:grid; gap:4px; min-width:0; padding-block:10px; border-bottom:1px solid var(--border-default); overflow-wrap:anywhere; }
.vehicle-dispatch__fields>div { display:grid; gap:8px; min-width:0; }
.vehicle-dispatch { min-width: 0; padding-block: 4px 20px; border-bottom: 1px solid var(--border-default); color: var(--text-primary); }
.vehicle-dispatch header { display: flex; justify-content: space-between; align-items: start; gap: 16px; }
.vehicle-dispatch h3 { margin: 0 0 8px; font-size: 18px; }
.vehicle-dispatch p { margin: 0; line-height: 1.6; font-size: 16px; overflow-wrap: anywhere; }
.vehicle-dispatch__fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr)); gap: 14px; margin-block: 18px; }
.vehicle-dispatch label { display: grid; gap: 8px; min-width: 0; font-size: 16px; }
.vehicle-dispatch select { width: 100%; min-width: 0; min-height: 44px; font: inherit; padding: 10px; color: var(--text-primary); background: var(--surface-raised); border: 1px solid var(--border-default); border-radius: var(--radius-sm, 6px); }
.vehicle-dispatch__status { display: grid; gap: 6px; }
.vehicle-dispatch small { font-size: 14px; line-height: 1.6; color: var(--text-secondary); }
.vehicle-dispatch progress { display: block; width: 100%; height: 8px; margin-top: 12px; accent-color: #84d7b9; }
.vehicle-dispatch__actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 16px; }
.vehicle-dispatch__actions button { display: inline-flex; align-items: center; justify-content: center; gap: 8px; min-height: 44px; flex: 1 1 120px; padding: 10px 12px; font: inherit; font-size: 16px; background: var(--surface-raised); color: var(--text-primary); border: 1px solid var(--border-default); border-radius: var(--radius-sm, 6px); cursor: pointer; }
.vehicle-dispatch__actions button.vehicle-dispatch__primary { background: var(--action-primary); }
.vehicle-dispatch__actions button:disabled { opacity: .55; cursor: not-allowed; }
.vehicle-dispatch :is(button,select):focus-visible { outline: 2px solid var(--action-focus); outline-offset: 3px; }
.vehicle-dispatch__service { margin-top: 24px; padding-top: 20px; border-top: 1px solid var(--border-default); }
.vehicle-dispatch h4 { margin: 0 0 10px; font-size: 17px; }
.vehicle-dispatch__patient { margin-top: 14px; }
.vehicle-dispatch__hint { margin-top: 10px !important; color: var(--text-secondary); }
.vehicle-dispatch__history { margin-top: 20px; border-top: 1px solid var(--border-default); padding-top: 8px; }
.vehicle-dispatch__history summary { min-height: 44px; padding-block: 12px; font-size: 16px; cursor: pointer; }
.vehicle-dispatch__history ol { padding-left: 22px; margin: 4px 0 12px; }
.vehicle-dispatch__history li { padding-block: 10px; line-height: 1.6; }
</style>
