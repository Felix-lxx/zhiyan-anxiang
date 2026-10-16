// Isolated visual fixture: no API credentials, no database mutations, real Three.js assets.
import { createApp, h, reactive, ref } from 'vue'
import DigitalTwinArena from '../src/components/DigitalTwinArena.vue'
import VehicleDispatchPanel from '../src/components/VehicleDispatchPanel.vue'
import UiDrawer from '../src/components/ui/UiDrawer.vue'
import type { Vehicle } from '../src/domain/drill'
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
  elapsed: 0, preview: false, vehiclesOpen: false,
  simulation: {
    fire: { intensity: 18, smoke_radius: 4, temperature: 70 },
    environment: { south_lane: 'open', east_hydrant: 'available', visibility: 90 },
    sensors: { temperature: 70, smoke_ppm: 50, alarm: true },
    residents: [{ id: 'resident-test', label: '居民测试员', vulnerable: false, status: 'moving', x: 50, y: 40, progress: 0, exit: 'north' as const, behavior: '正在疏散', last_location: '一楼走廊', queue_seconds: 0, smoke_exposure: 1.2 }],
    vehicles: [{ id: 'firetruck-1', name: '消防车 F-01', kind: 'firetruck', x: 50, y: 70, state: 'idle', reason: '在南门待命，选择道路节点安排到场。', minimum_width: 3.5, target_name: '', target_node_id: null, mission_id: null, current_edge_id: null, progress: 0, remaining_seconds: null, route_points: [], route_edge_ids: [] }] as Vehicle[],
    summary: { total: 1, evacuated: 0, moving: 1, vulnerable: 0 },
  },
})
const preview = { kind: 'robot' as const, title: '巡检机器人 → 北门集合点', can_apply: true, expected_sequence: 4, notice: '确认后加入任务队列；需要等待前一任务完成。', planned_duration_seconds: 42, route_distance: 35, risk_score: 18, queue_position: 2, impact: { congested_before: 2, congested_after: 1, smoke_exposed_before: 1, smoke_exposed_after: 1, forecast_horizon_seconds: 30 }, score_impact: { before: 60, after: 63, delta: 3, note: '此处为布局验收数据，不代表实际演练成绩。' } }
const arena = ref<InstanceType<typeof DigitalTwinArena>>()
Object.assign(window, { arenaQA: {
  vehicles(value: boolean) { state.vehiclesOpen = value },
  preview(value: boolean) { state.preview = value },
  focus() { arena.value?.focusResident('resident-test') },
  move() { state.elapsed++; Object.assign(state.simulation.residents[0]!, { y: 42, last_location: '楼门外道路', queue_seconds: 8, smoke_exposure: 2.3 }) },
} })
createApp({ setup: () => () => h('main', { class: ['operations-center--immersive', { 'space-preview-open': state.preview, 'detail-panel-open': state.vehiclesOpen }], 'data-ui-theme': 'immersive', 'data-mode': 'command' }, [
  h('header', { class: 'director-topbar' }, '演练布局验收 · 不连接后端'),
  h('div', { class: 'director-stage' }, [
    h(DigitalTwinArena, { ref: arena, status: 'running', elapsedSeconds: state.elapsed, simulation: state.simulation, robot: { state: 'idle', battery: 96, x: 50, y: 70, route: [], reason: '等待任务' }, interactive: true, effectsEnabled: false, operationPreview: state.preview ? preview : null, onCancelAction: () => { state.preview = false } }),
    h('nav', { class: 'director-rail' }, '任务 / 事件 / 助手'),
state.vehiclesOpen ? h(UiDrawer, { class: 'director-drawer', title: '处置任务', subtitle: '车辆调度布局验收', onClose: () => { state.vehiclesOpen = false } }, { default: () => h('div', { class: 'drawer-list' }, [h(VehicleDispatchPanel, { vehicles: state.simulation.vehicles, nodes: [{ id: 'north', name: '北门路口' }, { id: 'building', name: '老旧住宅楼门外消防车临时停靠位置' }], running: true, busy: false })]) }) : null,
    h('footer', { class: 'exercise-timeline' }, '现场事件时间线'),
  ]),
]) }).mount('#app')
