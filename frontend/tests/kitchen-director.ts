import {createApp,h,ref} from 'vue'
import DigitalTwinArena from '../src/components/DigitalTwinArena.vue'
import IndoorFirePanel from '../src/components/IndoorFirePanel.vue'
import TaskWorkflow from '../src/components/TaskWorkflow.vue'
import type {ExerciseTask} from '../src/domain/task'
import UiDrawer from '../src/components/ui/UiDrawer.vue'
import {kitchenPreview} from './kitchen-fixture.mjs'
import '../src/styles.css'
import '../src/styles/tokens.css'
import '../src/styles/base.css'
import '../src/styles/components.css'
import '../src/styles/responsive.css'
import '../src/director.css'
import '../src/director-layout.css'
import '../src/atlas-director.css'
import '../src/styles/director-readability.css'
const simulation=ref(kitchenPreview().simulation),open=ref(false),selectedDoor=ref<string>(),activeFloor=ref(2),arena=ref<InstanceType<typeof DigitalTwinArena>>()
const taskOpen=ref(false)
const task:ExerciseTask={id:'fixture-gas',title:'切断燃气并核验阀门状态',target:'示例楼二层东侧厨房燃气阀',target_floor:2,kind:'gas_off',status:'verifying',deadline_seconds:180,remaining_seconds:120,responsible_role:'物业/网格员',blockers:['处置还需 4 秒'],can_submit:false,operation:{mode:'arrival_receipt',duration_seconds:8,elapsed_seconds:4,remaining_seconds:4,phase:'working'}}
createApp({setup:()=>()=>h('main',{class:['operations-center--immersive atlas-director',{'drawer-open':open.value,'detail-panel-open':open.value}],'data-ui-theme':'immersive',style:'height:100dvh'},[
 h('div',{class:'director-stage'},[h(DigitalTwinArena,{ref:arena,simulation:simulation.value,status:'running',elapsedSeconds:60,robot:null,interactive:true,onIndoorFocus:value=>{activeFloor.value=value.floor},onInspectIndoor:id=>{selectedDoor.value=id;open.value=true}}),
 open.value?h(UiDrawer,{class:'director-drawer',section:'missions',title:'厨房演练 · 室内处置',onClose:()=>{open.value=false}},()=>h('div',{class:'drawer-list'},[...(taskOpen.value?[h('button',{onClick:()=>{taskOpen.value=false}},'返回室内现场'),h(TaskWorkflow,{task,running:true,busy:false,director:true})]:[h(IndoorFirePanel,{tasks:[task],onTask:()=>{taskOpen.value=true},state:simulation.value.environment.indoor,selectedDoorId:selectedDoor.value,activeFloor:activeFloor.value,onFocus:floor=>{arena.value?.focusIndoorFloor(floor)},onDoor:value=>{const current=simulation.value;simulation.value={...current,environment:{...current.environment,indoor:{...current.environment.indoor,doors:current.environment.indoor.doors.map(door=>door.id===value.door_id?{...door,state:value.state}:door)}}}}})])])):null]),
])}).mount('#app')
