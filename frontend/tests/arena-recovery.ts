// Isolated visual fixture: no API credentials, no database mutations, real Three.js assets.
import { createApp, h, reactive, ref } from 'vue'
import DigitalTwinArena from '../src/components/DigitalTwinArena.vue'
import VehicleDispatchPanel from '../src/components/VehicleDispatchPanel.vue'
import UiDrawer from '../src/components/ui/UiDrawer.vue'
import GuidedExercise from '../src/components/GuidedExercise.vue'
import DirectorTopbar from '../src/components/DirectorTopbar.vue'
import SceneAssistant from '../src/components/SceneAssistant.vue'
import ExecutionFeedback from '../src/components/ExecutionFeedback.vue'
import type { Vehicle, CommandReceipt } from '../src/domain/drill'
import type { AgentLiveState } from '../src/domain/agent'
import '../src/styles/tokens.css'
import '../src/styles.css'
import '../src/styles/base.css'
import '../src/styles/components.css'
import '../src/styles/responsive.css'
import '../src/director.css'
import '../src/director-layout.css'
import '../src/atlas-director.css'
import '../src/styles/director-readability.css'

const state = reactive({
  commands:[] as CommandReceipt[],
  elapsed: 0, preview: false, vehiclesOpen: false, coachOpen: false, assistantOpen: false,
  agentPreview: [] as Array<{id:string;route_points:Array<{x:number;y:number;height?:number}>}>,
  agentFeed:null as AgentLiveState|null, connection:undefined as 'connecting'|'live'|'stale'|undefined,
  simulation: {
    spatial_network: { nodes: [], edges: [] },
    world: new URLSearchParams(location.search).has('rescue') ? {
      schema_version: 3, parameters: { start_time: '20:15' }, fire_origin: { x: 20, y: 50 },
      objects: [
        { id: 'water', name: '西侧消火栓', type: 'fire_hydrant', x: 30, y: 70, width: 1, depth: 1, floors: 1, entry: { x: 30, y: 70 } },
        { id: 'home', name: '接运演示楼', type: 'building', x: 55, y: 50, width: 14, depth: 12, floors: 6, entry: { x: 47, y: 50 } },
      ],
    } : undefined,
    road_network: new URLSearchParams(location.search).has('rescue') ? {
      nodes: [{ id: 'north', name: '北门路口', x: 20, y: 45, is_exit: true }, { id: 'south', name: '南门路口', x: 20, y: 80, is_exit: true }],
      edges: [{ id: 'lane', name: '应急通道', start: { x: 20, y: 45 }, end: { x: 20, y: 80 }, width_meters: 5, status: 'open' as const, blocked_by_event: false, risk_score: 0 }],
    } : undefined,
    fire: { intensity: 18, smoke_radius: 4, temperature: 70 },
    environment: { south_lane: 'open', east_hydrant: 'available', visibility: 90 },
    sensors: { temperature: 70, smoke_ppm: 50, alarm: true },
    residents: [{ id: 'resident-test', label: '居民测试员', vulnerable: false, status: 'moving', x: 50, y: 40, progress: 0, exit: 'north' as const, behavior: '正在疏散', last_location: '一楼走廊', queue_seconds: 0, smoke_exposure: 1.2 }],
    helpers: [{id:'helper-test',staff_id:'escort-1',staff_name:'模拟值守员 1',resident_id:'resident-test',x:30,y:70,height:0,state:'approaching',responsible:'物业测试员',behavior:'沿通道前往会合',route_reachable:true,route_points:[{x:30,y:70},{x:30,y:40},{x:50,y:40}]}],
    vehicles: [{ id: 'firetruck-1', name: '消防车 F-01', kind: 'firetruck', x: 50, y: 70, state: 'idle', reason: '在南门待命，选择道路节点安排到场。', minimum_width: 3.5, target_name: '', target_node_id: null, mission_id: null, current_edge_id: null, progress: 0, remaining_seconds: null, route_points: [], route_edge_ids: [] }] as Vehicle[],
    summary: { total: 1, evacuated: 0, moving: 1, vulnerable: 0, missing: 0 },
  },
})
const preview = { kind: 'robot' as const, title: '巡检机器人 → 北门集合点', can_apply: true, expected_sequence: 4, notice: '确认后加入任务队列；需要等待前一任务完成。', planned_duration_seconds: 42, route_distance: 35, risk_score: 18, queue_position: 2, impact: { congested_before: 2, congested_after: 1, smoke_exposed_before: 1, smoke_exposed_after: 1, forecast_horizon_seconds: 30 }, score_impact: { before: 60, after: 63, delta: 3, note: '此处为布局验收数据，不代表实际演练成绩。' } }
const arena = ref<InstanceType<typeof DigitalTwinArena>>()
Object.assign(window, { arenaQA: {
  commands(value:CommandReceipt[]){state.commands=value;state.vehiclesOpen=true;state.assistantOpen=false;state.preview=false;state.coachOpen=false},
  agentStream(value:AgentLiveState|null,connection?:'connecting'|'live'|'stale'){state.agentFeed=value;state.connection=connection},
  coach(value: boolean) { state.coachOpen = value; state.vehiclesOpen = false; state.preview = false; state.assistantOpen = false },
  assistant(value: boolean) { state.assistantOpen = value; state.vehiclesOpen = false; state.preview = false },
  vehicles(value: boolean) { state.vehiclesOpen = value },
  rescue(kind: 'spray' | 'load') {
    state.elapsed = 12
    const vehicle = state.simulation.vehicles[0]!
    vehicle.kind = kind === 'spray' ? 'firetruck' : 'ambulance'
    vehicle.id = kind === 'spray' ? 'firetruck-1' : 'ambulance-1'
    vehicle.name = kind === 'spray' ? '消防车 F-01' : '救护车 A-01'
    vehicle.x = 20; vehicle.y = 70; vehicle.minimum_width = kind === 'spray' ? 3.5 : 2.8
    vehicle.state = 'arrived'
    vehicle.service = { action_id: 'visual-rescue-' + kind, vehicle_id: vehicle.id, action: kind, label: kind === 'spray' ? '喷水压制' : '接近并上车', status: 'executing', progress: .3, reason: kind === 'spray' ? '有效供水中，火势和烟气实时下降' : '担架组正沿集合通道返回救护车', starts_at_seconds: 0, ends_at_seconds: 45, duration_seconds: 45, remaining_seconds: 33, water_source: { id: 'water', name: '东侧消火栓', x: 57, y: 68 }, target: { x: 62, y: 55 }, resident_id: 'resident-test', resident_label: '居民测试员', pickup_points: [{ x: 50, y: 40 }, { x: 50, y: 70 }], approach_seconds: 5 }
    Object.assign(state.simulation.residents[0]!, { medical_transfer: kind === 'load' ? { phase: 'loading', vehicle_id: vehicle.id } : undefined })
    Object.assign(vehicle.service, { water_source: kind === 'spray' ? { id: 'water', name: '西侧消火栓', x: 30, y: 70 } : undefined, target: { x: 20, y: 50 }, resident_label: kind === 'load' ? '居民测试员' : undefined, pickup_points: [{ x: 20, y: 50 }, { x: 20, y: 70 }] })
    Object.assign(state.simulation.residents[0]!, { x: 20, y: 58 })
  },
  rescueFocus() { arena.value?.focusPoint(20, 60) },
  preview(value: boolean) { state.preview = value },
  focus() { arena.value?.focusResident('resident-test') },
  move() { state.elapsed++; Object.assign(state.simulation.residents[0]!, { y: 42, last_location: '楼门外道路', queue_seconds: 8, smoke_exposure: 2.3 }) },
} })
createApp({ setup: () => () => h('main', { class: ['operations-center--immersive atlas-director', { 'space-preview-open': state.preview, 'detail-panel-open': state.vehiclesOpen || state.assistantOpen, 'assistant-open': state.assistantOpen, 'coach-open': state.coachOpen && !state.vehiclesOpen && !state.preview && !state.assistantOpen }], 'data-ui-theme': 'immersive', 'data-mode': 'command' }, [
  h(DirectorTopbar, { name: '演练布局验收 · 不连接后端', subtitle: '隔离场景', socketState: 'live', statusLabel: '已结束', displayClock: '05:00', drillStatus: 'ended', busy: false, coachOpen: state.coachOpen, replay: false, onToggleCoach: () => { state.coachOpen = !state.coachOpen; state.vehiclesOpen = false; state.preview = false } }),
  state.assistantOpen ? h(SceneAssistant, { open: true, apiBaseUrl: '/__layout_api__', accessToken: 'layout-only', drillId: 'layout-only', drillName: '布局验收', atSeconds: null, liveSeconds: 0, agentFeed:state.agentFeed,connection:state.connection, onClose: () => { state.assistantOpen = false }, onPlanPreview: people => { state.agentPreview = people }, onNavigate: action=>{state.assistantOpen=false;if(action.resident_id)arena.value?.focusResident(action.resident_id)} }) : null,
  h('div', { class: 'director-stage' }, [
    h('nav', { class: 'atlas-director-modes', 'aria-label': '导演台模式' }, ['观察', '指挥', '复盘'].map(label => h('button', label))),
    state.coachOpen ? h(GuidedExercise, { drill: { status: 'ended', engine_version: 3, elapsed_seconds: 300, participants: [], events: [], tasks: [], robot: null, simulation: state.simulation }, busy: false, replay: false, onClose: () => { state.coachOpen = false }, onTasks: () => { state.vehiclesOpen = true }, onCompare: () => { state.coachOpen = false; state.preview = true } }) : null,
    h(DigitalTwinArena, { ref: arena, status: 'running', elapsedSeconds: state.elapsed, simulation: state.simulation, routePreview: state.agentPreview, robot: { state: 'idle', battery: 96, x: 50, y: 70, route: [], reason: '等待任务' }, interactive: true, effectsEnabled: false, operationPreview: state.preview ? preview : null, onCancelAction: () => { state.preview = false }, onDispatchVehicle: () => { state.preview = false; state.vehiclesOpen = true } }),
    h('nav', { class: 'director-rail' }, '任务 / 事件 / 助手'),
state.vehiclesOpen ? h(UiDrawer, { class: 'director-drawer', title: '处置任务', subtitle: state.commands.length?'执行回执布局核对':'车辆调度布局验收', onClose: () => { state.vehiclesOpen = false } }, { default: () => h('div', { class: 'drawer-list' }, state.commands.length?[h(ExecutionFeedback,{commands:state.commands,paused:false,score:{total_score:64,details:[],recommendations:[]}})]:[h(VehicleDispatchPanel, { vehicles: state.simulation.vehicles, nodes: [{ id: 'north', name: '北门路口' }, { id: 'building', name: '老旧住宅楼门外消防车临时停靠位置' }], running: true, busy: false })]) }) : null,
    h('footer', { class: 'exercise-timeline' }, '现场事件时间线'),
  ]),
]) }).mount('#app')
