<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import type {IndoorState} from '../domain/indoor'
interface Occupant {id:string;label:string;building_id?:string;current_floor?:number;floor?:number;indoor_stage?:string;status:string;behavior?:string;route_reachable?:boolean;queue_seconds?:number}
const props=defineProps<{state:IndoorState;readonly?:boolean;busy?:boolean;activeFloor?:number;residents?:Occupant[]}>()
const emit=defineEmits<{door:[value:{door_id:string;state:'open'|'closed'}];focus:[floor:number];resident:[id:string];select:[ids:string[]]}>()
const selected=ref<number>()
watch(()=>[props.state.building_id,props.activeFloor],()=>{selected.value=props.activeFloor},{immediate:true})
const floors=computed(()=>[...new Set(props.state.zones.map(zone=>zone.floor))].filter(floor=>floor>0).sort((a,b)=>a-b))
const floor=computed(()=>selected.value??props.state.zones.find(zone=>zone.id===props.state.source_zone_id)?.floor??1)
const zones=computed(()=>props.state.zones.filter(zone=>zone.floor===floor.value))
const doors=computed(()=>props.state.doors.filter(door=>door.floor===floor.value))
const people=computed(()=>(props.residents??[]).filter(person=>person.building_id===props.state.building_id&&person.indoor_stage!=='outdoor'&&person.status!=='evacuated'&&Math.max(1,Math.ceil(person.current_floor??person.floor??1))===floor.value))
const blocked=computed(()=>people.value.filter(person=>person.route_reachable===false).length)
</script>
<template>
  <section class="indoor-fire-panel" aria-label="楼内烟气与房门">
    <header><h3>楼内烟气与房门</h3><p>{{state.source_label}}</p></header>
    <label>观察楼层<select :value="floor" @change="selected=Number(($event.target as HTMLSelectElement).value);emit('focus',floor)"><option v-for="level in floors" :key="level" :value="level">{{level}} 层</option></select></label>
    <section class="indoor-fire-panel__people" aria-label="本层人员">
      <div class="indoor-fire-panel__heading"><h4>本层及下行楼梯</h4><span>{{people.length}} 人 · {{blocked}} 人路径受阻</span></div>
      <p v-if="!people.length">当前楼层没有待疏散居民。</p>
      <ul v-else><li v-for="person in people" :key="person.id"><div><strong>{{person.label}}</strong><span>{{person.behavior??person.status}} · 累计排队 {{Math.round(person.queue_seconds??0)}} 秒</span></div><button type="button" @click="emit('resident',person.id)">定位</button></li></ul>
      <button v-if="people.length" type="button" :disabled="readonly||busy" @click="emit('select',people.map(person=>person.id))">选择本层 {{people.length}} 人，预览疏散路线</button>
    </section>
    <ul class="indoor-fire-panel__zones"><li v-for="zone in zones" :key="zone.id"><strong>{{zone.name}}</strong><span>烟气 {{Math.round(zone.smoke_density*100)}}% · 可见度 {{zone.visibility}}% · {{zone.temperature}} ℃</span><meter :value="zone.smoke_density" min="0" max="1" :aria-label="zone.name+'烟气浓度'"/></li></ul>
    <p>关门减少烟气交换，同时阻断通行。房内或门口有人时，系统会拒绝关门。</p>
    <div v-for="door in doors" :key="door.id" class="indoor-fire-panel__door"><div><strong>{{door.label}}</strong><span>{{door.state==='open'?'打开 · 可通行':'关闭 · 暂不可通行'}}</span></div><button type="button" :disabled="readonly||busy" @click="emit('door',{door_id:door.id,state:door.state==='open'?'closed':'open'})">{{door.state==='open'?'关闭房门':'打开房门'}}</button></div>
  </section>
</template>
<style scoped>
.indoor-fire-panel button,.indoor-fire-panel select { color:var(--text-primary); background:var(--surface-panel); border:1px solid var(--border-default); border-radius:var(--radius-sm); }
.indoor-fire-panel button:not(:disabled):hover { border-color:var(--action-primary); background:var(--surface-raised); }
.indoor-fire-panel button:disabled { opacity:.55; cursor:not-allowed; }
.indoor-fire-panel button:focus-visible,.indoor-fire-panel select:focus-visible { outline:2px solid var(--action-primary); outline-offset:3px; }
.indoor-fire-panel__people { margin-block:24px; }
.indoor-fire-panel__heading { display:flex; align-items:baseline; flex-wrap:wrap; gap:8px 16px; }
.indoor-fire-panel__heading h4 { margin:0; font-size:18px; }
.indoor-fire-panel__heading>span { font-size:14px; }
.indoor-fire-panel__people ul { list-style:none; padding:0; margin:12px 0; }
.indoor-fire-panel__people li { display:flex; align-items:center; justify-content:space-between; gap:12px; padding-block:12px; border-bottom:1px solid var(--border-default); }
.indoor-fire-panel__people li>div { min-width:0; }
.indoor-fire-panel__people li span { display:block; font-size:14px; overflow-wrap:anywhere; }
.indoor-fire-panel__people>button { width:100%; white-space:normal; text-align:left; }
.indoor-fire-panel{font-size:16px;line-height:1.65;border-bottom:1px solid var(--border-default);padding-bottom:24px;min-width:0}.indoor-fire-panel h3{margin:0;font-size:20px}.indoor-fire-panel p{margin:10px 0 18px}.indoor-fire-panel label{display:flex;align-items:center;justify-content:space-between;gap:16px}.indoor-fire-panel select,.indoor-fire-panel button{min-height:44px;font:inherit;padding:8px 12px;max-width:100%}.indoor-fire-panel__zones{list-style:none;margin:16px 0;padding:0}.indoor-fire-panel__zones li{padding:12px 0;border-bottom:1px solid var(--border-default)}.indoor-fire-panel__zones strong,.indoor-fire-panel__zones span,.indoor-fire-panel__door span{display:block;overflow-wrap:anywhere}.indoor-fire-panel__zones span{font-size:14px}.indoor-fire-panel meter{display:block;width:100%;height:10px;margin-top:8px}.indoor-fire-panel__door{display:flex;align-items:center;flex-wrap:wrap;justify-content:space-between;gap:12px;padding-block:12px}.indoor-fire-panel__door>div{flex:1 1 220px}.indoor-fire-panel__door span{font-size:14px}.indoor-fire-panel__door button{flex-shrink:0}
</style>
