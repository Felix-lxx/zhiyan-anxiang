import {createApp,h,reactive,ref} from 'vue'
import DigitalTwinArena from '../src/components/DigitalTwinArena.vue'
import IndoorFirePanel from '../src/components/IndoorFirePanel.vue'
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
const simulation=reactive(kitchenPreview().simulation),open=ref(false),arena=ref<InstanceType<typeof DigitalTwinArena>>()
createApp({setup:()=>()=>h('main',{class:'operations-center--immersive atlas-director','data-ui-theme':'immersive',style:'height:100dvh'},[
 h('div',{class:'director-stage'},[h(DigitalTwinArena,{ref:arena,simulation,status:'running',elapsedSeconds:60,robot:null,interactive:true,onInspectIndoor:()=>{open.value=true}}),
 open.value?h(UiDrawer,{class:'director-drawer',section:'missions',title:'厨房演练 · 室内处置',onClose:()=>{open.value=false}},()=>h('div',{class:'drawer-list'},[h(IndoorFirePanel,{state:simulation.environment.indoor,onFocus:floor=>{open.value=false;arena.value?.focusIndoorFloor(floor)},onDoor:value=>{const door=simulation.environment.indoor.doors.find(item=>item.id===value.door_id);if(door)door.state=value.state}})])):null]),
])}).mount('#app')
