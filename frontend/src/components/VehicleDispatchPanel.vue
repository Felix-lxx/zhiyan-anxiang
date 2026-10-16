<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Vehicle, SpatialIntent } from '../domain/drill'
import AppIcon from './AppIcon.vue'
const props = defineProps<{ vehicles: Vehicle[]; nodes: Array<{ id: string; name: string }>; running: boolean; busy: boolean; selectedId?: string }>()
const emit = defineEmits<{ preview: [intent: SpatialIntent]; command: [id: string, command: 'cancel' | 'replan']; focus: [vehicle: Vehicle] }>()
const chosen = ref(''), target = ref('')
watch(() => props.selectedId, id => { if (id) chosen.value = id }, { immediate: true })
watch(() => props.vehicles.map(v => v.id).join(','), () => { if (!props.vehicles.some(v => v.id === chosen.value)) chosen.value = props.vehicles[0]?.id ?? '' }, { immediate: true })
watch(() => props.nodes, nodes => { if (!nodes.some(n => n.id === target.value)) target.value = '' })
const vehicle = computed(() => props.vehicles.find(v => v.id === chosen.value))
const active = computed(() => vehicle.value?.state === 'moving' || vehicle.value?.state === 'blocked')
const labels = { idle: '待命', moving: '前往现场', blocked: '通道受阻', arrived: '已到场' }
</script>

<template>
  <section v-if="vehicles.length" class="vehicle-dispatch" aria-label="应急车辆调度">
    <header><div><h3>应急车辆</h3><p>选择车辆和道路节点，预览路线后确认出发。</p></div><AppIcon name="route" :size="22" /></header>
    <div class="vehicle-dispatch__fields">
      <label>调度车辆<select v-model="chosen"><option v-for="item in vehicles" :key="item.id" :value="item.id">{{ item.name }} · {{ labels[item.state] }}</option></select></label>
      <label>到场位置<select v-model="target" :disabled="active || !running"><option value="" disabled>选择道路节点</option><option v-for="node in nodes" :key="node.id" :value="node.id">{{ node.name }}</option></select></label>
    </div>
    <template v-if="vehicle">
      <div class="vehicle-dispatch__status" role="status"><strong>{{ labels[vehicle.state] }}<span v-if="vehicle.remaining_seconds !== null"> · 剩余 {{ vehicle.remaining_seconds }} 秒</span></strong><p>{{ vehicle.reason }}</p><small>通行宽度需求 {{ vehicle.minimum_width }} 米 · {{ running ? '与演练时钟同步' : '当前时刻已冻结' }}</small></div>
      <progress v-if="active || vehicle.state === 'arrived'" :value="vehicle.progress" max="1" aria-label="车辆到场进度" />
      <div class="vehicle-dispatch__actions">
        <button type="button" @click="emit('focus', vehicle)"><AppIcon name="target" :size="16" />定位车辆</button>
        <template v-if="active"><button type="button" :disabled="!running || busy" @click="emit('command', vehicle.id, 'replan')">重算路线</button><button type="button" :disabled="!running || busy" @click="emit('command', vehicle.id, 'cancel')">取消行程</button></template>
        <button v-else type="button" class="vehicle-dispatch__primary" :disabled="!running || busy || !target" @click="emit('preview', { kind: 'vehicle', vehicleId: vehicle.id, targetNodeId: target })"><AppIcon name="route" :size="16" />预览到场路线</button>
      </div>
    </template>
  </section>
</template>

<style scoped>
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
</style>
