<script setup lang="ts">
import {computed} from 'vue'
import type {IndoorState} from '../domain/indoor'
import {indoorPlanFrame,shortRoomName} from '../domain/indoor-plan'
import AppIcon from './AppIcon.vue'

interface PlanResident {id:string;x:number;y:number;status:string;vulnerable?:boolean;building_id?:string;floor?:number;current_floor?:number;indoor_stage?:string}
const props=defineProps<{state:IndoorState;floor:number;selectedZoneId?:string;selectedDoorId?:string;residents?:PlanResident[]}>()
const emit=defineEmits<{zone:[id:string];door:[id:string];passage:[id:string]}>()
const zones=computed(()=>props.state.zones.filter(z=>z.floor===props.floor))
const passages=computed(()=>props.state.navigation?.passages.filter(e=>e.floors.includes(props.floor))??[])
const frame=computed(()=>indoorPlanFrame(zones.value,passages.value.flatMap(e=>[e.start,e.end])))
const rooms=computed(()=>zones.value.filter(z=>z.kind==='room'))
const entrances=computed(()=>zones.value.filter(z=>z.kind==='entry_hall'))
const doors=computed(()=>props.state.doors.filter(d=>d.floor===props.floor))
const report=computed(()=>props.state.navigation?.floors.find(f=>f.floor===props.floor))
const selected=computed(()=>rooms.value.find(z=>z.id===props.selectedZoneId))
const selectedDoor=computed(()=>doors.value.find(d=>d.id===props.selectedDoorId))
const people=computed(()=>(props.residents??[]).filter(p=>p.status!=='evacuated'&&p.indoor_stage!=='outdoor'
  &&p.building_id===props.state.building_id&&Math.max(1,Math.ceil(p.current_floor??p.floor??1))===props.floor))
const visiblePeople=computed(()=>people.value.slice(0,24))
const doorName=(roomId:string)=>{const zone=rooms.value.find(z=>z.id===roomId);return zone?shortRoomName(zone):'房间'}
const smokeColor=(density:number)=>density>=.45?'#844e41':density>=.15?'#625b3e':'#244e45'
</script>

<template>
  <section class="indoor-floor-plan" aria-label="当前楼层平面与三维联动">
    <div class="indoor-floor-plan__heading"><h4>{{floor}} 层现场平面</h4><span>点房间，同步三维</span></div>
    <div v-if="frame" class="indoor-floor-plan__canvas">
      <svg viewBox="0 0 480 300" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
        <g v-for="zone in zones.filter(z=>z.kind==='stairs')" :key="zone.id"><rect v-bind="frame.rect(zone)" fill="#243f41" stroke="#91bdb0" stroke-width="1.5" stroke-dasharray="5 4"/></g>
        <rect v-for="zone in entrances" :key="zone.id" v-bind="frame.rect(zone)" fill="#455b45" stroke="#b8b390" stroke-width="1.5"/>
        <line v-for="edge in passages" :key="edge.id" :x1="frame.point(edge.start.x,edge.start.y).x" :y1="frame.point(edge.start.x,edge.start.y).y"
          :x2="frame.point(edge.end.x,edge.end.y).x" :y2="frame.point(edge.end.x,edge.end.y).y" stroke-linecap="round"
          :stroke="edge.status==='blocked'||edge.geometry_blocked?'#e99379':(edge.density_percent??0)>=55?'#e5c280':'#6caa99'"
          :stroke-width="Math.max(3,Math.min(20,edge.width_meters*frame.scale))" opacity=".7"/>
        <g v-for="(zone,index) in rooms" :key="zone.id" class="indoor-floor-plan__room" @click="emit('zone',zone.id)">
          <rect v-bind="frame.rect(zone)" :fill="smokeColor(zone.smoke_density)" :stroke="zone.id===selectedZoneId?'#f1d298':zone.id===state.source_zone_id?'#efac8b':'#87b0a4'" :stroke-width="zone.id===selectedZoneId?4:2"/>
          <text :x="frame.rect(zone).x+10" :y="frame.rect(zone).y+28" fill="#f5efda" font-size="26" font-weight="600">{{index+1}}</text>
        </g>
        <g v-for="door in doors.filter(d=>d.portal)" :key="door.id">
          <line :x1="frame.point(door.portal!.x-door.portal!.normal_y*door.portal!.width/2,door.portal!.y+door.portal!.normal_x*door.portal!.width/2).x"
            :y1="frame.point(door.portal!.x-door.portal!.normal_y*door.portal!.width/2,door.portal!.y+door.portal!.normal_x*door.portal!.width/2).y"
            :x2="frame.point(door.portal!.x+door.portal!.normal_y*door.portal!.width/2,door.portal!.y-door.portal!.normal_x*door.portal!.width/2).x"
            :y2="frame.point(door.portal!.x+door.portal!.normal_y*door.portal!.width/2,door.portal!.y-door.portal!.normal_x*door.portal!.width/2).y"
            :stroke="door.state==='closed'?'#ffaf8b':'#abefd5'" stroke-width="5"/>
        </g>
        <circle v-for="person in visiblePeople" :key="person.id" :cx="frame.point(person.x,person.y).x" :cy="frame.point(person.x,person.y).y"
          r="4" :fill="person.vulnerable?'#f2ce87':'#f4f7e7'" stroke="#122e29" stroke-width="1.5"/>
      </svg>
    </div>
    <p v-else>该楼层暂无可用空间，切换到其他楼层后查看。</p>
    <ul class="indoor-floor-plan__legend" aria-label="平面图图例"><li><i class="is-path"/>通道</li><li><i class="is-closed"/>关闭房门</li><li><i class="is-person"/>人员</li><li><i class="is-priority"/>重点人员</li></ul>
    <nav class="indoor-floor-plan__rooms" aria-label="选择三维房间"><button v-for="(zone,index) in rooms" :key="zone.id" type="button" :aria-pressed="selectedZoneId===zone.id"
      :aria-label="`定位三维房间：${zone.name}`" @click="emit('zone',zone.id)"><AppIcon v-if="zone.id===state.source_zone_id" name="fire" :size="18"/><span>{{index+1}} · {{shortRoomName(zone)}}</span></button></nav>
    <p v-if="people.length>24">显示前 24 个人员标记，本层共有 {{people.length}} 人；完整名单见下方人员区。</p>
    <div class="indoor-floor-plan__selection" aria-live="polite">
      <template v-if="selected"><strong>{{selected.name}}</strong><p>{{selected.id===state.source_zone_id?'本场起火房间 · ':''}}烟气训练指数 {{Math.round(selected.smoke_density*100)}} / 100</p></template>
      <p v-else>选择房间查看三维近景；房门操作仍需核对人员与烟气。</p>
    </div>
    <nav v-if="doors.length" aria-label="在平面图中选择房门" class="indoor-floor-plan__doors">
      <button v-for="door in doors" :key="door.id" type="button" :aria-label="`核对房门：${door.label}`" :aria-pressed="door.id===selectedDoorId" @click="emit('door',door.id)">
        <AppIcon name="door" :size="18"/><span>{{door.kind==='apartment_entry'?state.dwellings?.find(unit=>unit.door_id===door.id)?.apartment_number+'户入户门':doorName(door.room_id)+'房门'}}<br/><small>{{door.state==='closed'?'关闭 · 通行受阻':door.can_close===false?'打开 · 仍有人员':'打开 · 已清空'}}</small></span>
      </button>
    </nav>
    <p v-if="selectedDoor" class="indoor-floor-plan__door-note">已选 {{selectedDoor.label}}，下方显示占用校验与开关操作。</p>
    <div v-if="report" class="indoor-floor-plan__report"><strong>本层待办</strong><p>{{report.reason}}</p><span>待疏散 {{report.total}} 人 · 待接应 {{report.needs_assistance}} 人 · 排队 {{report.queued}} 人<template v-if="report.unconfirmed"> · 待确认通知 {{report.unconfirmed}} 人</template></span><button v-if="report.critical_passage_id" type="button" @click="emit('passage',report.critical_passage_id)"><AppIcon name="target" :size="18"/>定位排队通道</button></div>
  </section>
</template>

<style scoped>
.indoor-floor-plan{margin-block:20px 28px;min-width:0;font-size:16px;line-height:1.65}
.indoor-floor-plan__heading{display:flex;justify-content:space-between;align-items:baseline;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.indoor-floor-plan h4{font-size:18px;margin:0}.indoor-floor-plan__heading>span{font-size:14px}
.indoor-floor-plan__canvas{position:relative;aspect-ratio:8/5;background:#142e29;border:1px solid var(--border-default);border-radius:8px;overflow:hidden;isolation:isolate}
.indoor-floor-plan__canvas>svg{display:block;width:100%;height:100%}
.indoor-floor-plan button{font:inherit;color:var(--text-primary);min-height:44px;border:1px solid var(--border-default);border-radius:8px;background:var(--surface-panel);padding:8px 12px;cursor:pointer;max-width:100%}
.indoor-floor-plan__room{cursor:pointer}
.indoor-floor-plan__rooms{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}
.indoor-floor-plan__rooms button{display:flex;align-items:center;gap:8px;flex:1 1 130px;justify-content:center}
.indoor-floor-plan button[aria-pressed=true]{border-color:#f1d298;color:#f1d298}
.indoor-floor-plan button:focus-visible{outline:2px solid #abefd5;outline-offset:3px}
.indoor-floor-plan__legend{display:flex;flex-wrap:wrap;gap:8px 16px;list-style:none;padding:0;margin:12px 0;font-size:14px}
.indoor-floor-plan__legend li{display:flex;align-items:center;gap:6px}.indoor-floor-plan i{display:inline-block;width:10px;height:10px;background:#6caa99}
.indoor-floor-plan .is-closed{background:#ffaf8b}.indoor-floor-plan .is-person{background:#f4f7e7;border-radius:50%}.indoor-floor-plan .is-priority{background:#f2ce87;border-radius:50%}
.indoor-floor-plan__selection{padding-block:12px;border-block:1px solid var(--border-default)}.indoor-floor-plan p{margin:6px 0;overflow-wrap:anywhere}
.indoor-floor-plan__selection p,.indoor-floor-plan__door-note,.indoor-floor-plan__report>span{font-size:14px}
.indoor-floor-plan__doors{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:16px}
.indoor-floor-plan__doors button{display:flex;align-items:center;justify-content:flex-start;gap:8px;text-align:left;overflow-wrap:anywhere;padding:10px}
.indoor-floor-plan small{font-size:14px}.indoor-floor-plan__report{margin-top:20px}.indoor-floor-plan__report button{display:flex;align-items:center;gap:6px;margin-top:12px}
@media(max-width:360px){.indoor-floor-plan__doors{grid-template-columns:minmax(0,1fr)}}
</style>
