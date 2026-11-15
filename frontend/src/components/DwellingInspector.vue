<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import type {IndoorDwelling} from '../domain/indoor'
import AppIcon from './AppIcon.vue'

const props=defineProps<{dwellings:IndoorDwelling[];floor:number;selectedZoneId?:string;selectedDoorId?:string;historical?:boolean}>()
const emit=defineEmits<{zone:[id:string];door:[id:string];household:[id:string]}>()
const local=ref('')
const units=computed(()=>props.dwellings.filter(unit=>unit.floor===props.floor))
const current=computed(()=>units.value.find(unit=>unit.id===local.value)??units.value[0])
watch(()=>[props.floor,props.selectedZoneId,props.selectedDoorId],()=>{
  const unit=units.value.find(item=>[item.kitchen_zone_id,item.entrance_zone_id].includes(props.selectedZoneId??'')
    ||[item.door_id,item.kitchen_door_id].includes(props.selectedDoorId??''))
  local.value=unit?.id??''
},{immediate:true})
const notice=computed(()=>({confirmed:'已确认收到',sent:'已通知，待收到回执',unnotified:'尚未核实通知'}[current.value?.notification_state??'unnotified']))
</script>
<template>
  <section v-if="units.length" class="dwelling-inspector" aria-label="本层住户与独立户门">
    <h4>按户组织行动</h4>
    <nav aria-label="选择本层住户"><button v-for="unit in units" :key="unit.id" type="button" :aria-pressed="current?.id===unit.id" @click="local=unit.id;emit('zone',unit.kitchen_zone_id)"><AppIcon name="building" :size="18"/><span>{{unit.apartment_number}} 户 · {{unit.resident_ids.length}} 人</span></button></nav>
    <template v-if="current">
      <strong>{{current.label}}</strong>
      <p>{{current.remaining}} 人待到场<template v-if="current.priority"> · {{current.priority}} 人待重点接应</template><template v-if="current.household_id"> · {{notice}}</template></p>
      <dl><div><dt>厨房门</dt><dd>{{current.kitchen_door_state==='closed'?'关闭，限制烟气交换':'打开'}}</dd></div><div><dt>入户门</dt><dd>{{current.entrance_state==='closed'?'关闭，暂不可撤离':'打开，可通行'}}</dd></div><div><dt>玄关烟气</dt><dd>训练指数 {{Math.round(current.entrance_smoke*100)}} / 100</dd></div></dl>
      <p class="dwelling-inspector__path">厨房 → 厨房门 → 玄关 → 入户门 → 公共走廊。到户核查停在入户门外。</p>
      <div class="dwelling-inspector__actions"><button type="button" @click="emit('door',current.door_id)"><AppIcon name="door" :size="18"/>核对入户门</button><button v-if="current.household_id&&!historical" type="button" @click="emit('household',current.household_id)"><AppIcon name="phone" :size="18"/>{{current.notification_state==='confirmed'?'查看住户回执':'核实本户通知'}}</button></div>
    </template>
  </section>
</template>
<style scoped>
.dwelling-inspector{margin-block:24px;min-width:0;font-size:16px;line-height:1.65}
h4{font-size:18px;margin:0 0 12px}nav,.dwelling-inspector__actions{display:flex;flex-wrap:wrap;gap:8px}nav{margin-bottom:16px}
button{display:flex;align-items:center;justify-content:center;gap:6px;min-height:44px;flex:1 1 140px;max-width:100%;font:inherit;white-space:normal;overflow-wrap:anywhere;padding:8px 12px;border:1px solid var(--border-default);border-radius:8px;background:var(--surface-panel);color:var(--text-primary);cursor:pointer}
button[aria-pressed=true]{border-color:#f1d298;color:#f1d298}button:focus-visible{outline:2px solid #a4ddc6;outline-offset:3px}
p{margin:8px 0;overflow-wrap:anywhere}dl{margin:12px 0}dl>div{display:flex;gap:12px;justify-content:space-between;padding-block:6px;border-bottom:1px solid var(--border-default);font-size:14px}dt{flex-shrink:0}dd{margin:0;text-align:right;overflow-wrap:anywhere}.dwelling-inspector__path{font-size:14px;margin-block:12px 16px}
</style>
