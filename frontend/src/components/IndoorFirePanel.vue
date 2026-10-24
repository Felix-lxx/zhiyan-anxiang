<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import type {IndoorState} from '../domain/indoor'
import type {ExerciseTask} from '../domain/task'
interface Occupant {id:string;label:string;building_id?:string;current_floor?:number;floor?:number;indoor_stage?:string;status:string;behavior?:string;route_reachable?:boolean;queue_seconds?:number}
const props=defineProps<{state:IndoorState;tasks?:ExerciseTask[];readonly?:boolean;busy?:boolean;activeFloor?:number;selectedDoorId?:string;residents?:Occupant[]}>()
const emit=defineEmits<{door:[value:{door_id:string;state:'open'|'closed'}];focus:[floor:number];resident:[id:string];select:[ids:string[]];task:[id:string]}>()
const selected=ref<number>()
watch(()=>[props.state.building_id,props.activeFloor],()=>{selected.value=props.activeFloor},{immediate:true})
const floors=computed(()=>[...new Set(props.state.zones.map(zone=>zone.floor))].filter(floor=>floor>0).sort((a,b)=>a-b))
const floor=computed(()=>selected.value??props.state.zones.find(zone=>zone.id===props.state.source_zone_id)?.floor??1)
const zones=computed(()=>props.state.zones.filter(zone=>zone.floor===floor.value))
const doors=computed(()=>props.state.doors.filter(door=>door.floor===floor.value).sort((a,b)=>Number(b.id===props.selectedDoorId)-Number(a.id===props.selectedDoorId)))
const people=computed(()=>(props.residents??[]).filter(person=>person.building_id===props.state.building_id&&person.indoor_stage!=='outdoor'&&person.status!=='evacuated'&&Math.max(1,Math.ceil(person.current_floor??person.floor??1))===floor.value))
const blocked=computed(()=>people.value.filter(person=>person.route_reachable===false).length)
const source=computed(()=>props.state.zones.find(zone=>zone.id===props.state.source_zone_id))
const hottest=computed(()=>[...zones.value].sort((a,b)=>b.smoke_density-a.smoke_density)[0])
const roomTasks=computed(()=>(props.tasks??[]).filter(task=>['gas_off','containment'].includes(task.kind??'')&&(task.target_floor??source.value?.floor)===floor.value))
const gasValve=computed(()=>props.state.devices?.find(device=>device.room_id===props.state.source_zone_id))
const taskLabel=(task:ExerciseTask)=>task.status==='completed'?'已核验':task.verification_ready?'待提交证据':task.operation?.phase==='working'?`处置计时 ${task.operation.remaining_seconds} 秒`:({waiting:'等待火情确认',pending:'待接收',executing:'待到位回执',verifying:'待满足处置条件'}[task.status]??task.status)
const conditionLabel=(status:string)=>({moving:'沿通道撤离',waiting:'等待疏散通知',missing:'失联，等待搜寻',blocked:'路径受阻',evacuated:'已到集合点'}[status]??'等待现场更新')
</script>
<template>
  <section class="indoor-fire-panel" aria-label="楼内烟气与房门">
    <header><p>{{state.source_label}}</p></header>
    <p v-if="state.equipment_notice" class="indoor-fire-panel__notice">{{state.equipment_notice}}</p>
    <p v-else-if="state.equipment_layout_version" class="indoor-fire-panel__equipment">火点位于灶台作业面；人员沿房门通道行动。</p>
    <label>观察楼层<select :value="floor" @change="selected=Number(($event.target as HTMLSelectElement).value);emit('focus',floor)"><option v-for="level in floors" :key="level" :value="level">{{level}} 层</option></select></label>
    <p v-if="readonly" class="indoor-fire-panel__notice">当前为只读观察。继续演练后可操作房门和分配疏散路线。</p>
    <div class="indoor-fire-panel__situation" aria-live="polite">
      <span>{{floor===source?.floor?'当前为起火层':'起火点在 '+source?.floor+' 层'}}<template v-if="hottest"> · 本层最高烟气 {{Math.round(hottest.smoke_density*100)}}%</template></span>
      <button v-if="source&&floor!==source.floor" type="button" @click="selected=source.floor;emit('focus',source.floor)">返回起火层</button>
    </div>
    <section v-if="roomTasks.length" class="indoor-fire-panel__tasks" aria-label="本层处置任务">
      <h4>本层处置</h4>
      <p v-if="gasValve">燃气阀：{{gasValve.state==='closed'?'已关闭 · 任务证据已核验':'打开 · 尚未核验关闭'}}。状态来自演练回执。</p>
      <ul><li v-for="task in roomTasks" :key="task.id"><div><strong>{{task.title}}</strong><span>{{taskLabel(task)}}<template v-if="task.status!=='completed'&&task.status!=='waiting'"> · {{task.overdue?'已超时，可补救':'距截止 '+task.remaining_seconds+' 秒'}}</template></span></div><button type="button" @click="emit('task',task.id)">{{task.status==='completed'?'查看证据':'进入处置'}}</button></li></ul>
    </section>
    <section aria-label="本层房门" class="indoor-fire-panel__doors">
      <h4>房门与通行</h4>
      <p>关闭房门会减少烟气交换并阻断通行，先确认房内与门口人员已撤离。</p>
      <article v-for="door in doors" :key="door.id" class="indoor-fire-panel__door" :class="{'is-selected':door.id===selectedDoorId}">
        <div class="indoor-fire-panel__door-title"><strong>{{door.label}}</strong><span>{{door.id===selectedDoorId?'现场选中 · ':''}}{{door.state==='open'?'打开，可通行':'关闭，暂不可通行'}}</span></div>
        <p v-if="door.state==='open'&&door.can_close===false" class="indoor-fire-panel__warning">{{door.blocked_reason}}</p>
        <ul v-if="door.occupants?.length" class="indoor-fire-panel__occupants">
          <li v-for="person in door.occupants" :key="person.kind+person.id"><span>{{person.label}} · {{person.reason}}</span><button v-if="person.kind==='resident'&&person.id" type="button" @click="emit('resident',person.id)">定位人员</button></li>
        </ul>
        <p v-else-if="door.can_close===true">房内及门口已清空。</p>
        <button type="button" :disabled="readonly||busy||(door.state==='open'&&door.can_close===false)" :aria-label="(door.state==='open'?'关闭':'打开')+door.label" @click="emit('door',{door_id:door.id,state:door.state==='open'?'closed':'open'})">{{busy?'正在同步…':door.state==='open'?'关闭房门':'打开房门'}}</button>
      </article>
    </section>
    <section class="indoor-fire-panel__people" aria-label="本层人员">
      <div class="indoor-fire-panel__heading"><h4>本层及下行楼梯</h4><span>{{people.length}} 人 · {{blocked}} 人路径受阻</span></div>
      <p v-if="!people.length">当前楼层没有待疏散居民。</p>
      <ul v-else><li v-for="person in people" :key="person.id"><div><strong>{{person.label}}</strong><span>{{person.behavior??conditionLabel(person.status)}} · 累计排队 {{Math.round(person.queue_seconds??0)}} 秒</span></div><button type="button" @click="emit('resident',person.id)">定位</button></li></ul>
      <button v-if="people.length" type="button" :disabled="readonly||busy" @click="emit('select',people.map(person=>person.id))">选择本层 {{people.length}} 人，预览疏散路线</button>
    </section>
    <details class="indoor-fire-panel__environment"><summary>查看本层 {{zones.length}} 个分区的烟气与温度</summary><ul class="indoor-fire-panel__zones"><li v-for="zone in zones" :key="zone.id"><strong>{{zone.name}}</strong><span>烟气 {{Math.round(zone.smoke_density*100)}}% · 可见度 {{zone.visibility}}% · {{zone.temperature}} ℃</span><meter :value="zone.smoke_density" min="0" max="1" :aria-label="zone.name+'烟气浓度'"/></li></ul></details>
  </section>
</template>
<style scoped>
.indoor-fire-panel__tasks { margin-block:20px 24px; }
.indoor-fire-panel__tasks h4 { margin:0; font-size:18px; }
.indoor-fire-panel__tasks p,.indoor-fire-panel__tasks span { font-size:14px; }
.indoor-fire-panel__tasks ul { list-style:none; padding:0; margin:0; }
.indoor-fire-panel__tasks li { display:flex; align-items:center; flex-wrap:wrap; gap:12px; padding-block:12px; border-bottom:1px solid var(--border-default); }
.indoor-fire-panel__tasks li>div { flex:1 1 160px; min-width:0; overflow-wrap:anywhere; }
.indoor-fire-panel__tasks span { display:block; }
.indoor-fire-panel__situation { display:flex; align-items:center; flex-wrap:wrap; gap:8px; margin-block:12px 20px; font-size:14px; }
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
.indoor-fire-panel__doors h4 { margin:0; font-size:18px; }
.indoor-fire-panel__doors>p,.indoor-fire-panel__door p { font-size:14px; margin:8px 0; }
.indoor-fire-panel .indoor-fire-panel__door { display:grid; grid-template-columns:minmax(0,1fr); gap:8px; margin:0; border:0; border-bottom:1px solid var(--border-default); background:transparent; padding:16px 0; }
.indoor-fire-panel__door.is-selected { background:var(--surface-raised); padding:16px; outline:1px solid var(--action-primary); border-radius:var(--radius-sm); }
.indoor-fire-panel__door>button { justify-self:start; white-space:normal; }
.indoor-fire-panel__occupants { list-style:none; margin:0; padding:0; }
.indoor-fire-panel__occupants li { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:8px; font-size:14px; }
.indoor-fire-panel__occupants li>span { flex:1 1 160px; overflow-wrap:anywhere; }
.indoor-fire-panel__notice,.indoor-fire-panel__warning { color:var(--text-primary); }
.indoor-fire-panel__environment { border-top:1px solid var(--border-default); padding-block:16px; }
.indoor-fire-panel__environment summary { min-height:44px; cursor:pointer; overflow-wrap:anywhere; }
.indoor-fire-panel{font-size:16px;line-height:1.65;border-bottom:1px solid var(--border-default);padding-bottom:24px;min-width:0}.indoor-fire-panel h3{margin:0;font-size:20px}.indoor-fire-panel p{margin:10px 0 18px}.indoor-fire-panel label{display:flex;align-items:center;justify-content:space-between;gap:16px}.indoor-fire-panel select,.indoor-fire-panel button{min-height:44px;font:inherit;padding:8px 12px;max-width:100%}.indoor-fire-panel__zones{list-style:none;margin:16px 0;padding:0}.indoor-fire-panel__zones li{padding:12px 0;border-bottom:1px solid var(--border-default)}.indoor-fire-panel__zones strong,.indoor-fire-panel__zones span,.indoor-fire-panel__door span{display:block;overflow-wrap:anywhere}.indoor-fire-panel__zones span{font-size:14px}.indoor-fire-panel meter{display:block;width:100%;height:10px;margin-top:8px}.indoor-fire-panel__door{display:flex;align-items:center;flex-wrap:wrap;justify-content:space-between;gap:12px;padding-block:12px}.indoor-fire-panel__door>div{flex:1 1 220px}.indoor-fire-panel__door span{font-size:14px}.indoor-fire-panel__door button{flex-shrink:0}
</style>
