<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useSceneOverlayLayout } from '../composables/useSceneOverlayLayout'

const sceneUtilities = useSceneOverlayLayout()
import * as THREE from 'three'
import { createApartment, createChargingShed, createFireStation, createStreet, createStreetFurniture, createRoadBarrier } from '../three/communityModels'
import { SceneMaterials, displayHeight as legacyDisplayHeight } from '../three/sceneMaterials'
import { createPerson, createPatrolRobot, posePerson } from '../three/actors'
import { CrowdRenderer } from '../three/crowdRenderer'
import { ActorAssets, type ActorAssetStatus } from '../three/actorAssets'
import { ActorMotion } from '../three/actorMotion'
import { helperIdentity, helperPresentation, meetingRoute, presentHelpers, type HelperState } from '../three/helperPresentation'
import { VehicleVisuals } from '../three/vehicleVisuals'
import { RescueVisuals, type RescueResident } from '../three/rescueVisuals'
import type { Vehicle } from '../domain/drill'
import { FireEffects } from '../three/fireEffects'
import { IndoorFireVisuals } from '../three/indoorFireVisuals'
import { indoorCameraOffset } from '../three/indoorGeometry'
import { cutFloor, stairOpenings, floorContainsHeight } from '../three/indoorGeometry'
import type { IndoorState } from '../domain/indoor'
import { RoadVisuals } from '../three/roadVisuals'
import { createRouteGuide } from '../three/routeGuide'
import { assemblyAttendance, createAssemblyPoint, type AssemblyResident } from '../three/assemblyPoint'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import AppIcon from './AppIcon.vue'

interface Resident extends RescueResident { height?: number; building_id?: string; floor?: number; current_floor?: number; indoor_stage?: string; current_edge_id?: string | null; id: string; label: string; vulnerable: boolean; status: string; x: number; y: number; progress: number; exit?: 'north' | 'south'; behavior?: string; smoke_exposure?: number; congestion?: number; queue_seconds?: number; last_location?: string; assisted?: boolean; search_responsible?: string; speed_factor?: number; route_points?: Array<{ x: number; y: number; height?: number }>; route_edge_ids?: string[]; route_reachable?: boolean; estimated_seconds?: number }
interface SpatialEdgeState { id: string; kind: string; start: { x: number; y: number; height: number }; end: { x: number; y: number; height: number }; width_meters: number; density_percent?: number; live_occupancy?: number; waiting_count?: number; capacity_persons?: number }
interface RoadEdgeState { geometry_blocked?: boolean; blocked_reason?: string; reserved_by_vehicle?: string | null; id: string; name: string; start: { x: number; y: number }; end: { x: number; y: number }; width_meters: number; status: 'open' | 'restricted' | 'blocked'; blocked_by_event: boolean; risk_score: number; smoke_risk?: number; density_percent?: number; live_occupancy?: number; waiting_count?: number; capacity_persons?: number; flow_capacity_per_second?: number }
interface Simulation {
  vehicles?: Vehicle[]
  spatial_network?: { nodes: Array<{id:string;name:string;x:number;y:number;height:number;kind:string;floor:number;is_exit?:boolean;building_id?:string}>; edges: SpatialEdgeState[] }
  world?: { schema_version?: number; spatial_units?:{height_mode?:string}; parameters?: { start_time?: string; wind_direction?: string; fire_floor?:number }; fire_source?: { location: { object_id: string }; device_id?: string; ignition_position?: { x: number; y: number; height: number } }; objects: Array<{ id: string; name: string; type: string; x: number; y: number; width: number; depth: number; floors: number; entry: { x: number; y: number } }>; fire_origin: { x: number; y: number; height?:number } } | null
  helpers?: HelperState[]
  fire: { intensity: number; smoke_radius: number; temperature: number }
  environment: { indoor?:IndoorState; south_lane: string; east_hydrant: string; visibility: number; blockages?: Array<{ x: number; y: number; target: string; road_edge_id?: string }> }
  sensors: { temperature: number; smoke_ppm: number; alarm: boolean }
  residents: Resident[]
  summary: { total: number; evacuated: number; moving: number; vulnerable: number; missing?: number; smoke_exposed?: number; congested?: number; north_load?: number; south_load?: number }
  road_network?: { nodes: Array<{ id: string; name: string; x: number; y: number; is_exit: boolean }>; edges: RoadEdgeState[] }
}
interface Robot { state: string; battery: number; x: number; y: number; route: string[]; reason: string; task_queue?: Array<{ id: string; label: string; status: string; progress?: number; ends_at_seconds?: number; route_points?: Array<{ x: number; y: number; height?: number }> }> }
interface DrillEvent { sequence: number; event_type: string; message: string; payload?: { x?: number; y?: number; target?: string; route_points?: Array<{ x: number; y: number; height?: number }>; severity?: string } }
export interface AssistantSceneContext { kind: 'resident' | 'road' | 'robot' | 'object'; id?: string; label: string; type?: string; detail?: string; x?: number; y?: number }
type SelectedObject = { title: string; type: string; detail: string; action?: string; residentId?: string; roadEdgeId?: string; vehicleId?: string; x?: number; y?: number }
type SpatialIntent =
  | { kind: 'road'; edgeId: string }
  | { kind: 'robot'; x: number; y: number; target: string }
  | { kind: 'residents'; residentIds: string[]; exit: 'north' | 'south'; action: 'evacuate' | 'priority_assist' }
interface OperationPreview {
  rescue_action?: 'spray' | 'load' | 'handover'
  kind: 'road' | 'robot' | 'residents' | 'vehicle'; can_apply: boolean; title?: string; notice: string
  expected_sequence?: number
  route_points?: Array<{ x: number; y: number; height?: number }>; route_edge_ids?: string[]; route_distance?: number
  planned_duration_seconds?: number | null; queue_position?: number; risk_score?: number; width_meters?: number
  affected_residents?: number; affected_robot_tasks?: number; residents?: Resident[]; exit?: 'north' | 'south'; action?: 'evacuate' | 'priority_assist'
  impact?: { congested_before: number; congested_after: number; smoke_exposed_before: number; smoke_exposed_after: number; forecast_horizon_seconds: number }
  score_impact?: { before: number; after: number; delta: number; note: string }
}

const props = defineProps<{
  routePreview?: Array<{id:string;exit?:'north'|'south';route_kind?:'robot';route_points?: Array<{x:number;y:number;height?:number}>}>
  robotRoutePreview?: Array<{ x: number; y: number; height?: number }>
  operationPreview?: OperationPreview | null
  operationBusy?: boolean
  status: string
  elapsedSeconds: number
  robot: Robot | null
  simulation: Simulation | null
  interactive?: boolean
  events?: DrillEvent[]
  compact?: boolean
  worldLabel?: string
  effectsEnabled?: boolean
  highContrast?: boolean
  cameraEnabled?: boolean
  fireSourceSelection?: { enabled: boolean; selectedId: string; eligibleIds: string[] }
  roomSelection?: boolean
  indoorFloor?: number
}>()
const emit = defineEmits<{
  inject: [eventType: 'channel_blocked' | 'hydrant_failure' | 'resident_missing', context?: { x?: number; y?: number; target?: string; road_edge_id?: string }]
  robotCommand: [command: 'step' | 'broadcast' | 'replan']
  robotTarget: [context: { x: number; y: number; target: string }]
  residentCommand: [context: { residentIds: string[]; exit: 'north' | 'south'; action: 'evacuate' | 'priority_assist' }]
  previewAction: [intent: SpatialIntent]
  confirmAction: []
  cancelAction: []
  reopenRoad: [edgeId: string]
  selection: [ids: string[]]
  contextSelection: [context: AssistantSceneContext | null]
  askAssistant: [context: AssistantSceneContext]
  dispatchVehicle: [id: string]
  fireSourcePick: [objectId: string]
  fireRoomPick: [selection:{floor:number;room:string}]
  inspectIndoor: [doorId?: string]
  inspectDevice: [deviceId: string]
  indoorFocus: [value: { buildingId: string; floor: number }]
}>()

const host = ref<HTMLDivElement | null>(null)
const viewMode = ref<'director' | 'robot' | 'resident' | 'rescue'>('director')
const selected = ref<SelectedObject | null>(null)
const isDraggingEvent = ref(false)
const selectedResident = ref('')
const renderError = ref('')
const interactionNotice = ref('')
const toolMode = ref<'inspect' | 'block' | 'robot' | 'residents'>('inspect')
const selectedResidents = ref<string[]>([])
const directorCue = ref('')
const inspectorOpen = computed(() => Boolean(selected.value && viewMode.value !== 'resident' && toolMode.value !== 'residents' && !props.compact && !props.operationPreview && !props.operationBusy))

function assistantContext(value: SelectedObject | null): AssistantSceneContext | null {
  if (!value) return null
  const kind: AssistantSceneContext['kind'] = value.residentId ? 'resident' : value.roadEdgeId ? 'road' : value.action === 'robot' || /机器人|具身智能体/.test(value.title + value.type) ? 'robot' : 'object'
  return { kind, id: value.residentId ?? value.roadEdgeId, label: value.title, type: value.type, detail: value.detail, x: value.x, y: value.y }
}
function askAboutSelection(): void { const context = assistantContext(selected.value); if (context) emit('askAssistant', context) }
watch(selected, value => emit('contextSelection', assistantContext(value)), { deep: true })

let scene: THREE.Scene
let camera: THREE.PerspectiveCamera
let renderer: THREE.WebGLRenderer
let controls: OrbitControls
let animationFrame = 0
let resizeObserver: ResizeObserver
let robotGroup: THREE.Group
let routeLine: THREE.Line | null = null
let fireLight: THREE.PointLight
let ambientLight: THREE.HemisphereLight
let userOrbiting = false
const helperMeshes = new Map<string, THREE.Group>()
let groundPlane: THREE.Mesh
let blockageLayer: THREE.Group
let environmentAssetLayer: THREE.Group
let roadNetworkLayer: THREE.Group
let residentRouteLayer: THREE.Group
let residentTrailLayer: THREE.Group
let helperLinkLayer: THREE.Group
let indoorGeometry: THREE.Group
const marquee = ref<{left:number;top:number;width:number;height:number}|null>(null)
const sceneMaterials = new SceneMaterials()
let fireEffects: FireEffects
let lastFrameTime = 0
let visualSeconds = 0
let frameCount = 0
let sampleStarted = 0
const fps = ref(0)
const quality = ref<'low' | 'medium' | 'high'>(window.innerWidth < 760 ? 'low' : (navigator.hardwareConcurrency ?? 8) <= 4 ? 'medium' : 'high')
const residentMeshes = new Map<string, THREE.Group>()
let crowdRenderer: CrowdRenderer | undefined
const buildingMeshes = new Map<string, THREE.Object3D>()
const fireSourceMarkers = new Map<string, THREE.Mesh<THREE.RingGeometry, THREE.MeshBasicMaterial>>()
let fireCore: THREE.Mesh
let indoorFireVisuals: IndoorFireVisuals | undefined
const visibleIndoorFloor = ref<number>()
const visibleIndoorBuilding = ref('')
const indoorBuildings = computed(() => props.simulation?.world?.objects.filter(object => object.type === 'building' &&
  props.simulation?.spatial_network?.nodes.some(node => node.kind === 'corridor' && node.building_id === object.id)) ?? [])
const indoorFloors = computed(() => [...new Set(props.simulation?.spatial_network?.nodes.filter(node =>
  node.kind === 'corridor' && node.building_id === visibleIndoorBuilding.value).map(node => node.floor) ?? [])].sort((a, b) => a - b))
const residentTrails = new Map<string, THREE.Vector3[]>()
const residentTrailLines = new Map<string, THREE.Line>()
const helperLinkLines = new Map<string, THREE.Line>()
const stairHeatMeshes = new Map<string, THREE.Mesh>()
let roadHeatMesh: THREE.InstancedMesh | null = null
const indoorView = ref(false)
const showFireSource = computed(() => !props.simulation?.environment.indoor || !indoorView.value ||
  (visibleIndoorBuilding.value === props.simulation.environment.indoor.building_id && visibleIndoorFloor.value === props.simulation.world?.parameters?.fire_floor))
const displayToolsOpen = ref(false)
const interactiveMeshes: THREE.Object3D[] = []
const roadInteractiveMeshes = new Set<THREE.Object3D>()
const targetCameraPosition = new THREE.Vector3(66, 76, 74)
const targetLookAt = new THREE.Vector3(0, 0, 0)
const raycaster = new THREE.Raycaster()
const pointer = new THREE.Vector2()
const pointerStart = new THREE.Vector2()
const motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)')
let reducedMotion = motionPreference.matches || document.documentElement.dataset.reduceMotion === 'true'
let qualityFactor = quality.value === 'high' ? 1 : quality.value === 'medium' ? .72 : .45
let pageVisible = !document.hidden
let renderDirty = true
let destroyed = false
const roadVisuals = new RoadVisuals()
let residentRouteSignature = ''
let robotRouteSignature = ''
let lastEntitySeconds = -1
let blockageSignature = ''
const hydrantModels: Array<{ group: THREE.Group; paint: THREE.MeshStandardMaterial[]; warning: THREE.Mesh; isEast: boolean }> = []
const exitModels: Array<{ group: THREE.Group; materials: THREE.MeshStandardMaterial[]; nodeId?: string }> = []
const environmentRequests = new Set<AbortController>()
const assemblyModels = new Map<string, ReturnType<typeof createAssemblyPoint>>()
const assemblyNodes = computed(() => props.simulation?.spatial_network?.nodes.filter(node => node.kind === 'assembly' && /^assembly:(north|south)$/.test(node.id)) ?? [])
const selectedAssembly = computed(() => assemblyNodes.value.find(node => node.name === selected.value?.title && selected.value?.type === '集合点'))
const assemblyPeople = computed(() => (props.simulation?.residents ?? []) as Array<Resident & AssemblyResident>)
const assemblyCounts = computed(() => selectedAssembly.value ? assemblyAttendance(assemblyPeople.value, selectedAssembly.value.id) : null)
const assemblyPending = computed(() => selectedAssembly.value ? assemblyPeople.value.filter(person => person.node_id === selectedAssembly.value!.id && person.status === 'evacuated' && !person.counted) : [])
const actorAssetStatus = ref<ActorAssetStatus>('loading')
const retryingModels = ref(false)
const actorAssets = new ActorAssets(status => { actorAssetStatus.value = status; renderDirty = true })
async function retryActorModels() {
  if (retryingModels.value || destroyed) return
  retryingModels.value = true
  try { await actorAssets.retryFailed() }
  finally { retryingModels.value = false }
}
const actorMotion = new ActorMotion()
let vehicleVisuals: VehicleVisuals | null = null
let rescueVisuals: RescueVisuals | null = null
const currentRobotTask = computed(() => props.robot?.task_queue?.find(task => ['executing', 'blocked'].includes(task.status)))
const robotProgress = computed(() => Math.round(100 * Math.max(0, Math.min(1, currentRobotTask.value?.progress ?? (['arrived', 'completed'].includes(props.robot?.state ?? '') ? 1 : 0)))))
const robotRemaining = computed(() => currentRobotTask.value?.ends_at_seconds === undefined || currentRobotTask.value.status === 'blocked' ? null : Math.max(0, Math.ceil(currentRobotTask.value.ends_at_seconds - props.elapsedSeconds)))
const robotStateLabel = computed(() => ({ idle: '待命', executing: '前往目标', blocked: '路线受阻', arrived: '已到达 · 等待广播', completed: '广播已完成', sensing: '感知现场', inspecting: '现场巡检', scanning: '扫描现场', verifying: '现场复核' }[props.robot?.state ?? ''] ?? '等待状态同步'))
const actorAssetLabel = computed(() => actorAssetStatus.value === 'loading' ? '精细模型正在加载；可继续演练' : actorAssetStatus.value === 'fallback' ? '部分精细模型加载失败，已使用轻量模型；可原地重试' : '骨骼人物与巡检底盘已就绪；靠近对象查看细节')

const clockLabel = computed(() => `${String(Math.floor(props.elapsedSeconds / 60)).padStart(2, '0')}:${String(props.elapsedSeconds % 60).padStart(2, '0')}`)
const activeResident = computed(() => props.simulation?.residents.find((item) => item.id === selectedResident.value) ?? props.simulation?.residents.find((item) => item.status === 'moving'))
const activeHelper = computed(() => props.simulation?.helpers?.find((helper) => helper.resident_id === activeResident.value?.id))
const displayedHelpers = computed(() => presentHelpers(props.simulation?.helpers ?? []))
const escortStatusLabel = computed(() => {
  switch (activeHelper.value?.state) {
    case 'completed': return '已护送到达'
    case 'escorting': return '已会合同行'
    case 'blocked': return '会合路线受阻'
    case 'approaching': return '护送员接近中'
    default: return activeResident.value?.assisted
      ? activeResident.value.status === 'evacuated' ? '已护送到达' : '护送中'
      : '未指派'
  }
})
const stairCongestion = computed(() => {
  const stairs = props.simulation?.spatial_network?.edges.filter((edge) => edge.kind === 'stairs') ?? []
  return {
    count: stairs.reduce((total, edge) => total + (edge.live_occupancy ?? 0) + (edge.waiting_count ?? 0), 0),
    density: stairs.reduce((peak, edge) => Math.max(peak, edge.density_percent ?? 0), 0),
  }
})
const povExposureLevel = computed(() => Math.min(100, Math.round((activeResident.value?.smoke_exposure ?? 0) * 6)))
const latestRoutePoints = computed(() => props.robotRoutePreview?.length ? props.robotRoutePreview : props.robot?.task_queue?.find((item) => ['executing', 'blocked'].includes(item.status))?.route_points ?? props.robot?.task_queue?.filter((item) => item.status === 'completed').slice(-1)[0]?.route_points ?? [])
const toolHelp = computed(() => ({ inspect: '拖动旋转视角，滚轮缩放；点击对象查看实时状态。', block: '点击有颜色的真实路段：红色封锁、橙色受限，提交后立即重算所有 A* 路线。', robot: '点击任意空间目标，机器人会沿当前道路图逐段移动并持续回传进度。', residents: '点击或拖动框选居民；点击出口预览，确认后观察连续行走与队列。' }[toolMode.value]))
const accessibleObjects = computed(() => [
  ...(props.simulation?.vehicles?.map(v => ({ key: `vehicle:${v.id}`, label: v.name })) ?? []),
  ...(props.robot ? [{ key: 'robot', label: '巡检广播机器人 R-01' }] : []),
  ...(props.simulation?.world?.objects.filter(o=>o.type!=='assembly_point' || !assemblyNodes.value.length).map(o => ({ key: `object:${o.id}`, label: o.name })) ?? [{ key: 'building-3', label: '3 号重点疏散楼栋' }, { key: 'east-hydrant', label: '东侧消火栓' }, { key: 'south-exit', label: '南门出口' }]),
  ...(props.simulation?.road_network?.edges.map((edge) => ({ key: `road:${edge.id}`, label: `${edge.name}（${edge.status === 'blocked' ? '已封锁' : edge.status === 'restricted' ? '受限' : '畅通'}）` })) ?? []),
  ...assemblyNodes.value.map(node => ({ key: node.id, label: `${node.name}（到达核验）` })),
  ...(props.simulation?.residents.map((resident) => ({ key: resident.id, label: `${resident.label}${resident.vulnerable ? '（重点人员）' : ''}` })) ?? []),
])

function displayHeight(height=0):number { return props.simulation?.world?.spatial_units?.height_mode==='meters'?height:legacyDisplayHeight(height) }
function floorHeight(floor:number):number { return props.simulation?.world?.spatial_units?.height_mode==='meters'?(floor-1)*3.2+.18:floor*1.92 }
function worldPoint(x: number, y: number, height = 0): THREE.Vector3 {
  return new THREE.Vector3(x - 50, displayHeight(height), y - 50)
}

function material(color: number, roughness = 0.82, emissive = 0): THREE.MeshStandardMaterial {
  return new THREE.MeshStandardMaterial({ color, roughness, metalness: 0.06, emissive, emissiveIntensity: emissive ? 0.2 : 0 })
}

function roadDetail(edge: RoadEdgeState): string {
  if (edge.geometry_blocked) return `${edge.width_meters} 米 · 地图通行受阻 · ${edge.blocked_reason ?? '道路与楼体净距范围相交，请调整地图后新建场次。'}`
  const status = edge.status === 'blocked' ? '已封锁' : edge.reserved_by_vehicle ? '车辆通行管控 · 人员在入口等候' : edge.status === 'restricted' ? '通行受限' : '当前畅通'
  const capacity = edge.capacity_persons ? ` · 容量 ${edge.capacity_persons} 人` : ''
  const flow = edge.flow_capacity_per_second ? ` · 估算流量 ${edge.flow_capacity_per_second} 人/秒` : ''
  return `${edge.width_meters} 米 · ${status} · 综合风险 ${edge.risk_score} · 密度 ${edge.density_percent ?? 0}% · 通行 ${edge.live_occupancy ?? 0} 人 · 排队 ${edge.waiting_count ?? 0} 人${capacity}${flow}`
}

function register(object: THREE.Object3D, data: { title: string; type: string; detail: string; action?: string; residentId?: string; objectId?: string; fireRoom?:{floor:number;room:string}; x?: number; y?: number }): void {
  object.userData.selection = data
  object.traverse((child) => { child.userData.selection = data })
  interactiveMeshes.push(object)
}

function addBuilding(name: string, x: number, z: number, width: number, depth: number, floors: number): THREE.LOD {
  const hour = Number.parseInt(props.simulation?.world?.parameters?.start_time?.split(':')[0] ?? '20', 10)
  const seed = [...name].reduce((sum,char) => sum + char.charCodeAt(0),0)
  const lod = createApartment(width, depth, floors, seed, hour >= 18 || hour < 6, sceneMaterials)
  lod.position.set(x,0,z); scene.add(lod)
  register(lod, { title: name, type: `${floors} 层老旧住宅`, detail: '点击定位楼栋；使用楼内剖面查看居民与楼梯通行', x:x+50, y:z+50 })
  return lod
}

function addRoad(x: number, z: number, width: number, depth: number, rotation = 0): void {
  const roadGroup = new THREE.Group()
  const road = new THREE.Mesh(new THREE.BoxGeometry(width, .16, depth), material(0x2c3736, .98))
  road.position.y = .08; road.receiveShadow = true; roadGroup.add(road)
  const vertical = depth > width
  const length = vertical ? depth : width
  for (let offset = -length / 2 + 3; offset < length / 2 - 2; offset += 7) {
    const stripe = new THREE.Mesh(new THREE.BoxGeometry(vertical ? .14 : 2.4, .025, vertical ? 2.4 : .14), new THREE.MeshBasicMaterial({ color: 0xc4c4ad }))
    stripe.position.set(vertical ? 0 : offset, .18, vertical ? offset : 0); roadGroup.add(stripe)
  }
  const curbGeometry = new THREE.BoxGeometry(vertical ? .48 : length, .2, vertical ? length : .48)
  for (const side of [-1, 1]) {
    const curb = new THREE.Mesh(curbGeometry, material(0x69716c, .9)); curb.position.set(vertical ? side * (width / 2 + .25) : 0, .16, vertical ? 0 : side * (depth / 2 + .25)); curb.receiveShadow = true; roadGroup.add(curb)
  }
  roadGroup.position.set(x, 0, z); roadGroup.rotation.y = rotation; scene.add(roadGroup)
}

function addStreetLight(x: number, z: number, rotation = 0): void {
  const group = new THREE.Group()
  const pole = new THREE.Mesh(new THREE.CylinderGeometry(.1, .14, 5.4, 10), material(0x273b39, .35)); pole.position.y = 2.7; group.add(pole)
  const arm = new THREE.Mesh(new THREE.BoxGeometry(1.4, .1, .1), material(0x273b39, .35)); arm.position.set(.62, 5.28, 0); group.add(arm)
  const lamp = new THREE.Mesh(new THREE.BoxGeometry(.52, .18, .34), new THREE.MeshStandardMaterial({ color: 0xffe6a6, emissive: 0xffd06a, emissiveIntensity: 1.5 })); lamp.position.set(1.25, 5.18, 0); group.add(lamp)
  const hour=Number.parseInt(props.simulation?.world?.parameters?.start_time?.split(':')[0]??'20',10)
  if(hour>=18||hour<6){const light=new THREE.PointLight(0xffd091,18,13,2);light.position.set(1.25,4.9,0);group.add(light)}
  group.position.set(x, 0, z); group.rotation.y = rotation; scene.add(group)
}

function addParkedVehicle(x: number, z: number, color: number, rotation = 0): void {
  const group = new THREE.Group()
  const body = new THREE.Mesh(new THREE.BoxGeometry(3.4, .8, 1.7), material(color, .42)); body.position.y = .72; body.castShadow = true; group.add(body)
  const cabin = new THREE.Mesh(new THREE.BoxGeometry(1.8, .65, 1.45), new THREE.MeshStandardMaterial({ color: 0x273a3d, roughness: .35, metalness: .2 })); cabin.position.set(-.2, 1.38, 0); group.add(cabin)
  for (const wheelX of [-1.05, 1.05]) for (const wheelZ of [-.86, .86]) { const wheel = new THREE.Mesh(new THREE.CylinderGeometry(.3, .3, .16, 14), material(0x171c1b)); wheel.rotation.x = Math.PI / 2; wheel.position.set(wheelX, .4, wheelZ); group.add(wheel) }
  group.position.set(x, 0, z); group.rotation.y = rotation; scene.add(group)
}

async function loadEnvironmentAssets(): Promise<void> {
  const assetBase = `${import.meta.env.BASE_URL}assets/`
  const base = assetBase + 'kenney-city-suburban/Models/GLB%20format/'
  const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js')
  if (destroyed) return
  const loader = new GLTFLoader()
  const definitions = [
    { url: base+'tree-large.glb', size: 5, positions: [[-43,-38],[-42,38],[-15,35],[13,40],[42,12],[39,-39],[-16,-43]] },
    { url: base+'planter.glb', size: 1.8, positions: [[-9,8],[8,8],[19,8]] },
    { url: assetBase+'kenney-car-kit/sedan.glb', size: 4.2, positions: [[-45,-19],[-45,-11],[-45,-3]] },
    ...(!props.simulation?.vehicles?.length ? [
      { url: assetBase+'kenney-car-kit/firetruck.glb', size: 6.2, positions: [[40,36]] },
      { url: assetBase+'kenney-car-kit/ambulance.glb', size: 5.2, positions: [[40,44]] },
    ] : []),
  ]
  const isClear = (x: number,z: number,radius:number) => {
    const px=x+50, py=z+50
    if(props.simulation?.world?.objects.some(o=>Math.abs(o.x-px)<o.width/2+radius && Math.abs(o.y-py)<o.depth/2+radius)) return false
    return !(props.simulation?.road_network?.edges ?? []).some(edge=>{
      const dx=edge.end.x-edge.start.x, dy=edge.end.y-edge.start.y
      const t=THREE.MathUtils.clamp(((px-edge.start.x)*dx+(py-edge.start.y)*dy)/(dx*dx+dy*dy||1),0,1)
      return Math.hypot(px-edge.start.x-t*dx,py-edge.start.y-t*dy)<edge.width_meters/2+radius
    })
  }
  const results = await Promise.allSettled(definitions.map(async definition=>{
    const controller = new AbortController(); environmentRequests.add(controller)
    const timeout = window.setTimeout(() => controller.abort(), 15000)
    let gltf
    try {
      const response = await fetch(definition.url, { signal:controller.signal })
      if(!response.ok)throw new Error(`环境资源读取失败（${response.status}）`)
      gltf = await loader.parseAsync(await response.arrayBuffer(), definition.url.slice(0, definition.url.lastIndexOf('/')+1))
    } finally { window.clearTimeout(timeout); environmentRequests.delete(controller) }
    if(destroyed) {
      const temporary=new THREE.Group();temporary.add(gltf.scene);disposeLayer(temporary);return
    }
    const bounds=new THREE.Box3().setFromObject(gltf.scene), size=bounds.getSize(new THREE.Vector3()), center=bounds.getCenter(new THREE.Vector3())
    const scale=definition.size/Math.max(size.x,size.y,size.z,.01)
    const prototype=new THREE.Group(); gltf.scene.position.set(-center.x,-bounds.min.y,-center.z); prototype.add(gltf.scene)
    definition.positions.forEach(([x,z])=>{
      if(!isClear(x,z,definition.size/2)) return
      const model=prototype.clone(true);model.scale.setScalar(scale);model.position.set(x,0,z)
      model.traverse(object=>{const mesh=object as THREE.Mesh;if(mesh.isMesh){mesh.castShadow=qualityFactor===1;mesh.receiveShadow=true}})
      environmentAssetLayer.add(model)
      if(definition.url.includes('car-kit')) register(model,{title:definition.url.includes('firetruck')?'停放消防车':definition.url.includes('ambulance')?'停放救护车':'停放车辆',type:'社区环境模型',detail:'用于识别停车区域；当前为静态车辆，不执行救援任务。'})
    })
    renderDirty=true
  }))
  if(!destroyed) for(const building of props.simulation?.world?.objects.filter(o=>o.type==='building')??[]) {
    const x=building.x-50+building.width/2+3,z=building.y-50
    if(isClear(x,z,1.8)) { const furniture=createStreetFurniture();furniture.position.set(x,0,z);environmentAssetLayer.add(furniture) }
  }
  if(!destroyed)renderDirty=true
  if(!destroyed && results.some(result=>result.status==='rejected')) flashNotice('部分环境模型加载失败，演练可继续；刷新后重试。')
}

function addHydrant(name: string, x: number, z: number, isEast = false): void {
  const group = new THREE.Group()
  const unavailable = isEast && props.simulation?.environment.east_hydrant === 'failed'
  const base = new THREE.Mesh(new THREE.CylinderGeometry(.55, .7, 1.3, 16), material(isEast ? 0x8f3c32 : 0xb94838))
  base.position.y = .65; group.add(base)
  const cap = new THREE.Mesh(new THREE.SphereGeometry(.57, 16, 10), material(0xc75b43)); cap.position.y = 1.35; group.add(cap)
  const paint = [base.material, cap.material] as THREE.MeshStandardMaterial[]
  for(const side of [-1,1]) {
    const outlet=new THREE.Mesh(new THREE.CylinderGeometry(.24,.24,.58,12),material(0xa34131,.45));outlet.rotation.z=Math.PI/2;outlet.position.set(side*.6,.93,0);group.add(outlet)
    paint.push(outlet.material)
    const nut=new THREE.Mesh(new THREE.CylinderGeometry(.27,.27,.13,6),material(0xaaa698,.4));nut.rotation.z=Math.PI/2;nut.position.set(side*.92,.93,0);group.add(nut)
  }
  const flange=new THREE.Mesh(new THREE.CylinderGeometry(.73,.73,.14,16),material(0x616963,.6));flange.position.y=.12;group.add(flange)
  for(let i=0;i<6;i++){const bolt=new THREE.Mesh(new THREE.CylinderGeometry(.065,.065,.08,6),material(0xbab9a6,.45));bolt.position.set(Math.sin(i*Math.PI/3)*.61,.23,Math.cos(i*Math.PI/3)*.61);group.add(bolt)}
  group.scale.setScalar(.65)
  const warning = new THREE.Mesh(new THREE.RingGeometry(.9, 1.15, 24), new THREE.MeshBasicMaterial({ color: 0xe6a34a, side: THREE.DoubleSide }))
  warning.rotation.x = -Math.PI / 2; warning.position.y = .08; warning.visible=unavailable; group.add(warning)
  paint.forEach(m=>{m.userData.originalColor=m.color.getHex()})
  hydrantModels.push({group,paint,warning,isEast})
  group.position.set(x, 0, z); scene.add(group)
  register(group, { title: name, type: '消防水源', detail: isEast ? '东侧消火栓 · 可在演练中注入压力异常' : '备用消火栓 · 当前可用', action: isEast ? 'hydrant_failure' : undefined, x: x + 50, y: z + 50 })
}

function addExit(name: string, x: number, z: number): void {
  const group = new THREE.Group()
  const left = new THREE.Mesh(new THREE.BoxGeometry(.45, 3.8, .45), material(0x70a393, .6, 0x194c42)); left.position.set(-2.2, 1.9, 0); group.add(left)
  const right = left.clone(); right.position.x = 2.2; group.add(right)
  const top = new THREE.Mesh(new THREE.BoxGeometry(4.8, .45, .45), material(0x70a393, .6, 0x194c42)); top.position.y = 3.6; group.add(top)
  group.position.set(x, 0, z); scene.add(group)
  const node=props.simulation?.road_network?.nodes.find(item=>item.is_exit && (item.name===name || Math.hypot(item.x-x-50,item.y-z-50)<.5))
  exitModels.push({group,materials:[left.material,top.material] as THREE.MeshStandardMaterial[],nodeId:node?.id})
  register(group, { title: name, type: '安全出口', detail: '正在读取出口相邻路段状态', x: x + 50, y: Math.min(100, z + 50) })
}

function createFireSystem(): void {
  const origin = props.simulation?.world?.fire_source?.ignition_position ?? props.simulation?.world?.fire_origin
  const fx = origin ? origin.x - 50 : 13, fz = origin ? origin.y - 50 : -1
  const core = fireCore = new THREE.Mesh(new THREE.BoxGeometry(3,3,3), new THREE.MeshBasicMaterial({ visible: false }))
  core.position.set(fx, 1.5, fz); scene.add(core)
  register(core, { title: props.simulation?.environment.indoor ? '厨房起火点' : '充电棚起火点', type: props.simulation?.environment.indoor?'厨房火灾':'锂电池火灾', detail: '火势和烟气随服务端统一演练时钟演化' })
  fireLight = new THREE.PointLight(0xff4d1f, 7, 34, 1.4); fireLight.position.set(fx, 7, fz); scene.add(fireLight)
  fireEffects = new FireEffects(); fireEffects.group.position.set(fx,0,fz);scene.add(fireEffects.group)
}

function createRobot(): void {
  robotGroup = createPatrolRobot()
  const scan = new THREE.Mesh(new THREE.ConeGeometry(5.5, 12, 32, 1, true), new THREE.MeshBasicMaterial({ color: 0x42d4c8, transparent: true, opacity: .08, side: THREE.DoubleSide, depthWrite: false }))
  scan.rotation.x = -Math.PI / 2; scan.position.set(0, 1, -6); scan.visible=false;robotGroup.add(scan);robotGroup.userData.scan=scan
  robotGroup.position.copy(worldPoint(18, 53)); scene.add(robotGroup)
  register(robotGroup, { title: '巡检广播机器人 R-01', type: '具身智能体', detail: '点击后可推进感知—复核—上报—执行闭环', action: 'robot', x: 18, y: 53 })
  void actorAssets.robot(robotGroup)
}

function createResidents(): void {
  const residents = props.simulation?.residents ?? []
  const visibleResidents = residents
  for (const resident of visibleResidents) {
    const group = residents.length > 60 ? new THREE.Group() : createPerson(resident.id, resident.vulnerable)
    group.name = resident.id; group.userData.vulnerable = resident.vulnerable
    group.position.copy(worldPoint(resident.x, resident.y, resident.height)); scene.add(group); residentMeshes.set(resident.id, group)
    register(group, { title: resident.label, type: resident.vulnerable ? '重点关照人员' : '参演居民智能体', detail: resident.vulnerable ? '移动速度较慢，需要优先引导至集合点' : '根据告警、广播和道路状态执行疏散', residentId: resident.id, x: resident.x, y: resident.y })
    if (residents.length <= 60) void actorAssets.person(group, resident.id, resident.vulnerable)
  }
  if (residents.length > 60) {
    let slot = 0
    crowdRenderer = new CrowdRenderer([...residentMeshes.values()], () => {
      const model = createPerson(`crowd-detail-${slot++}`)
      void actorAssets.person(model, model.uuid)
      return model
    })
    scene.add(crowdRenderer.group); interactiveMeshes.push(crowdRenderer.group)
  }
}

function buildScene(): void {
  const hour = Number.parseInt(props.simulation?.world?.parameters?.start_time?.split(':')[0] ?? '20', 10)
  const night = hour >= 18 || hour < 6
  const background = night ? 0x142329 : 0xdde3e3
  scene = new THREE.Scene(); scene.background = new THREE.Color(background); scene.fog = new THREE.FogExp2(background, night ? .008 : .005)
  camera = new THREE.PerspectiveCamera(48, 1, .1, 400); camera.position.copy(targetCameraPosition)
  renderer = new THREE.WebGLRenderer({ antialias: qualityFactor === 1, powerPreference: 'high-performance' }); renderer.setPixelRatio(Math.min(window.devicePixelRatio, qualityFactor === 1 ? 1.5 : 1)); renderer.shadowMap.enabled = qualityFactor === 1; renderer.shadowMap.type = THREE.PCFShadowMap; renderer.outputColorSpace = THREE.SRGBColorSpace
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = night ? 1.3 : 1.05
  host.value?.appendChild(renderer.domElement)
  controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true; controls.dampingFactor = .075; controls.maxPolarAngle = Math.PI * .47; controls.minDistance = 2.5; controls.maxDistance = 145; controls.target.set(0, 0, 0); controls.addEventListener('change', markRenderDirty)
  controls.addEventListener('start', () => { userOrbiting = true })
  controls.addEventListener('end', () => { targetCameraPosition.copy(camera.position); targetLookAt.copy(controls.target); userOrbiting = false; renderDirty = true })
  ambientLight = new THREE.HemisphereLight(night ? 0x9ebacf : 0xffffff, 0x56624a, props.highContrast ? 3.2 : night ? .85 : 2.7); scene.add(ambientLight)
  const moon = new THREE.DirectionalLight(night ? 0xc4d4e8 : 0xfff3df, night ? 1.5 : 2.1); moon.position.set(-38, 62, 18); moon.castShadow = qualityFactor === 1; moon.shadow.mapSize.set(2048,2048); moon.shadow.camera.left = -65; moon.shadow.camera.right = 65; moon.shadow.camera.top = 65; moon.shadow.camera.bottom = -65; moon.shadow.normalBias = .045; moon.shadow.radius = 3; scene.add(moon)
  groundPlane = new THREE.Mesh(new THREE.PlaneGeometry(116, 116), sceneMaterials.surface('paving',0x999b88,36,36)); groundPlane.rotation.x = -Math.PI / 2; groundPlane.receiveShadow = true; scene.add(groundPlane)
  blockageLayer = new THREE.Group(); scene.add(blockageLayer)
  environmentAssetLayer = new THREE.Group(); scene.add(environmentAssetLayer)
  roadNetworkLayer = roadVisuals.group; scene.add(roadNetworkLayer)
  residentRouteLayer = new THREE.Group(); scene.add(residentRouteLayer)
  residentTrailLayer = new THREE.Group(); scene.add(residentTrailLayer)
  helperLinkLayer = new THREE.Group(); scene.add(helperLinkLayer)
  indoorGeometry = new THREE.Group(); scene.add(indoorGeometry); buildSpatialGeometry()
  if (props.simulation?.world) {
    buildFrozenCommunity()
  } else {
  const court = new THREE.Mesh(new THREE.CircleGeometry(12, 64), material(0x1b3631, .9)); court.rotation.x = -Math.PI / 2; court.position.set(-4, .02, 2); scene.add(court)
  const assemblyRing = new THREE.Mesh(new THREE.RingGeometry(6.2, 6.55, 64), new THREE.MeshBasicMaterial({ color: 0x69c8b8, transparent: true, opacity: .58, side: THREE.DoubleSide })); assemblyRing.rotation.x = -Math.PI / 2; assemblyRing.position.set(-4, .045, 2); scene.add(assemblyRing)
  addRoad(0, 0, 10, 104); addRoad(0, 0, 104, 9); addRoad(-26, 21, 8, 44); addRoad(28, -20, 8, 42)
  addBuilding('1 号楼', -30, -26, 18, 11, 6); addBuilding('2 号楼', -4, -28, 17, 11, 6); addBuilding('3 号楼', 27, -20, 18, 12, 7); addBuilding('4 号楼', -28, 25, 17, 12, 6); addBuilding('5 号楼', 25, 28, 19, 12, 6)
  const shed = new THREE.Mesh(new THREE.BoxGeometry(12, 2.8, 7), material(0x4b5550)); shed.position.set(13, 1.4, -1); shed.castShadow = true; scene.add(shed)
  addHydrant('东侧消火栓', 39, -3, true); addHydrant('西侧备用消火栓', -35, 7)
  addExit('北门出口', 0, -51); addExit('南门出口', 0, 51)
  ;[[-7,-17,0],[7,-17,Math.PI],[-7,18,0],[7,18,Math.PI],[-36,2,0],[35,4,Math.PI]].forEach(([x,z,rotation]) => addStreetLight(x, z, rotation))
  addParkedVehicle(-8, -7, 0x6e8f8b, Math.PI / 2); addParkedVehicle(8, 8, 0x9c6d5e, Math.PI / 2); addParkedVehicle(-20, 7, 0x66717b, 0)
  }
  createFireSystem(); createRobot(); createResidents(); updateEntities(); indoorGeometry.visible = false
  if(props.simulation?.environment.indoor) {
    indoorFireVisuals=new IndoorFireVisuals(props.simulation.environment.indoor,worldPoint,(object,data)=>register(object,data as Parameters<typeof register>[1]),props.simulation.spatial_network?.edges,()=>{renderDirty=true});scene.add(indoorFireVisuals.group)
    focusIndoorFloor(props.indoorFloor??props.simulation.world?.parameters?.fire_floor??1)
  }
  void loadEnvironmentAssets().catch(() => {
    if (!destroyed) flashNotice('精细环境资源暂不可用，基础现场和演练操作仍可使用。')
  })
  renderer.domElement.addEventListener('pointerdown', onPointerDown)
  renderer.domElement.addEventListener('pointerup', onPointerUp)
  renderer.domElement.addEventListener('pointermove', onPointerMove)
  renderer.domElement.addEventListener('pointercancel', cancelMarquee)
  renderer.domElement.addEventListener('webglcontextlost', onContextLost)
  renderer.domElement.addEventListener('webglcontextrestored', onContextRestored)
  document.addEventListener('visibilitychange', onVisibilityChange)
  resizeObserver = new ResizeObserver(resize); if (host.value) resizeObserver.observe(host.value)
  resize(); animate()
}

function resize(): void {
  if (!host.value || !renderer || !camera) return
  const { clientWidth, clientHeight } = host.value; renderer.setSize(clientWidth, clientHeight, false); camera.aspect = clientWidth / Math.max(1, clientHeight); camera.updateProjectionMatrix(); renderDirty = true
}

function markRenderDirty(): void { renderDirty = true }

function applyQuality(): void {
  qualityFactor=quality.value==='high'?1:quality.value==='medium'?.72:.45
  if(!renderer||!scene)return
  renderer.setPixelRatio(Math.min(window.devicePixelRatio,quality.value==='high'?1.5:quality.value==='medium'?1.25:1))
  renderer.shadowMap.enabled=quality.value!=='low'
  let lampCount=0
  scene.traverse(object=>{
    if(object instanceof THREE.DirectionalLight)object.castShadow=quality.value!=='low'
    if(object instanceof THREE.PointLight && object!==fireLight)object.visible=lampCount++<(quality.value==='high'?10:quality.value==='medium'?5:2)
    if(object instanceof THREE.LOD && object.levels[1] && !object.parent?.userData.actorLod)object.levels[1].distance=object.parent?.userData.limbs ? (quality.value==='high'?32:quality.value==='medium'?22:14) : (quality.value==='high'?150:quality.value==='medium'?100:55)
  })
  actorAssets.setQuality(quality.value)
  resize();renderDirty=true
}

function buildFrozenCommunity(): void {
  for (const edge of props.simulation?.road_network?.edges ?? []) {
    const street=createStreet(Math.hypot(edge.end.x-edge.start.x,edge.end.y-edge.start.y),Math.max(1.8,edge.width_meters),sceneMaterials)
    street.position.copy(worldPoint((edge.start.x+edge.end.x)/2,(edge.start.y+edge.end.y)/2))
    street.rotation.y=Math.atan2(edge.end.x-edge.start.x,edge.end.y-edge.start.y);scene.add(street)
    const length=Math.hypot(edge.end.x-edge.start.x,edge.end.y-edge.start.y)
    if(length>12) addStreetLight(street.position.x+(edge.end.y-edge.start.y)/length*(edge.width_meters/2+.8),street.position.z-(edge.end.x-edge.start.x)/length*(edge.width_meters/2+.8),street.rotation.y)
  }
  for (const object of props.simulation?.world?.objects ?? []) {
    const x = object.x - 50, z = object.y - 50
    if (object.type === 'building') { const building = addBuilding(object.name, x, z, object.width, object.depth, object.floors); buildingMeshes.set(object.id, building) }
    else if (object.type === 'fire_hydrant') addHydrant(object.name, x, z, /东/.test(object.name))
    else if (object.type === 'exit') addExit(object.name, x, z)
    else if (['charging_shed', 'micro_fire_station'].includes(object.type)) {
      const mesh = object.type === 'charging_shed' ? createChargingShed(object.width,object.depth) : createFireStation(object.width,object.depth)
      mesh.position.set(x, 0, z); scene.add(mesh)
      register(mesh, { title: object.name, type: object.type === 'charging_shed' ? '充电棚' : '微型消防站', detail: '本场次冻结地图对象 · 点击可指派机器人到接入点', objectId: object.id, x: object.entry.x, y: object.entry.y })
      if (object.type === 'charging_shed') {
        const radius = Math.max(object.width, object.depth) * .65 + 1
        const marker = new THREE.Mesh(new THREE.RingGeometry(radius, radius + .35, 48), new THREE.MeshBasicMaterial({ color: 0x95e5c6, side: THREE.DoubleSide, depthTest: false }))
        marker.rotation.x = -Math.PI / 2; marker.position.set(x, .25, z); marker.renderOrder = 20
        marker.userData.selection = { objectId: object.id }; marker.visible = false
        scene.add(marker); fireSourceMarkers.set(object.id, marker); interactiveMeshes.push(marker)
      }
    } else if (object.type === 'assembly_point' && !assemblyNodes.value.length) {
      const marker = createAssemblyPoint(object.name)
      marker.group.position.set(x, 0, z); scene.add(marker.group)
      register(marker.group, { title: object.name, type: '集合点', detail: '到达安全出口后，由参演人员逐人核验', x: object.entry.x, y: object.entry.y })
    }
    if (['building', 'exit', 'charging_shed'].includes(object.type) || (object.type === 'assembly_point' && !assemblyNodes.value.length)) {
      const canvas = document.createElement('canvas'); canvas.width = 384; canvas.height = 72
      const ctx = canvas.getContext('2d')!
      ctx.fillStyle = '#17352bed'; ctx.fillRect(0, 0, 384, 72); ctx.fillStyle = '#f4f4df'; ctx.font = '600 40px "Microsoft YaHei", sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(object.name, 192, 36, 370)
      const label = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), depthTest: true, transparent: true }))
      label.userData.buildingLabel = object.id
      label.position.set(x, object.type === 'building' ? object.floors * 3.2 + 2 : 4, z); label.scale.set(9, 1.7, 1); scene.add(label)
      if (object.type === 'charging_shed') register(label, { title: object.name, type: '充电棚', detail: '起火候选对象', objectId: object.id, x: object.entry.x, y: object.entry.y })
    }
  }
}

function buildSpatialGeometry(): void {
  const graph=props.simulation?.spatial_network
  if(!graph)return
  const homeId=props.simulation?.residents.find(p=>p.building_id)?.building_id
  const homes=props.simulation?.world?.objects.filter(o=>o.type==='building') ?? []
  for(const home of homes) {
    const belongs=(n: typeof graph.nodes[number]) => n.building_id ? n.building_id===home.id : home.id===homeId
    const levels=[...new Set(graph.nodes.filter(n=>n.kind==='corridor' && belongs(n)).map(n=>n.height))]
    for(const height of levels) {
      // Open stairwell on the west side; partial-height partitions retain a readable cutaway.
      const floor = new THREE.Group()
      const pieces = cutFloor({x:home.x,y:home.y,width:home.width*.96,depth:home.depth*.92},stairOpenings(graph.edges,height))
      for (const piece of pieces) {
        const slab = new THREE.Mesh(new THREE.BoxGeometry(piece.width,.12,piece.depth),sceneMaterials.surface('paving',0xafa994,2,2))
        slab.position.copy(worldPoint(piece.x,piece.y,height));slab.position.y-=.07;slab.receiveShadow=true;floor.add(slab)
      }
      floor.userData.slice={buildingId:home.id,low:height,high:height};indoorGeometry.add(floor)
      for(const side of [-1,1]) {
        const wall=new THREE.Mesh(new THREE.BoxGeometry(home.width*.63,.85,.1),material(0xbeb9a6))
        wall.position.copy(worldPoint(home.x+home.width*.16,home.y+side*home.depth*.46,height));wall.position.y+=.42;wall.userData.slice={buildingId:home.id,low:height,high:height};indoorGeometry.add(wall)
      }
      const rooms=graph.nodes.filter(n=>n.kind==='room'&&n.height===height&&belongs(n))
      const seenRooms = new Set<string>()
      for(const room of rooms) {
        if(props.simulation?.environment.indoor?.building_id===home.id)continue
        const key = `${room.x}:${room.y}:${room.height}`
        if (seenRooms.has(key)) continue
        seenRooms.add(key)
        const door=new THREE.Group(),frameMaterial=material(0x8b7257,.75)
        for(const side of [-1,1]){const jamb=new THREE.Mesh(new THREE.BoxGeometry(.065,2.1,.12),frameMaterial);jamb.position.set(side*.43,1.05,0);door.add(jamb)}
        const lintel=new THREE.Mesh(new THREE.BoxGeometry(.92,.08,.12),frameMaterial);lintel.position.y=2.12;door.add(lintel)
        const hall=graph.nodes.find(n=>n.kind==='corridor'&&n.height===height&&belongs(n))
        if(hall){door.position.copy(worldPoint((room.x+hall.x)/2,(room.y+hall.y)/2,room.height));door.rotation.y=Math.atan2(hall.x-room.x,hall.y-room.y)}
        else door.position.copy(worldPoint(room.x,room.y,room.height))
        door.userData.slice={buildingId:home.id,low:height,high:height};indoorGeometry.add(door)
      }
    }
  }
  const drawnConnections = new Set<string>()
  for(const edge of graph.edges.filter(e=>e.id.startsWith('space:') && !e.id.includes(':resident-') || e.kind==='room')) {
    const visualKey=JSON.stringify([edge.kind,edge.start,edge.end,edge.width_meters])
    if (drawnConnections.has(visualKey)) continue
    drawnConnections.add(visualKey)
    const firstChild = indoorGeometry.children.length
    const a=worldPoint(edge.start.x,edge.start.y,edge.start.height), b=worldPoint(edge.end.x,edge.end.y,edge.end.height)
    a.y+=.035;b.y+=.035
    const horizontal=Math.hypot(b.x-a.x,b.z-a.z), rise=Math.abs(b.y-a.y)
    if(horizontal>.05) {
      const width=Math.max(.6,edge.width_meters), yaw=Math.atan2(b.x-a.x,b.z-a.z)
      if(edge.kind==='stairs' && rise>.05) {
        const steps=Math.max(2,Math.ceil(rise/.18))
        const geometry=new THREE.BoxGeometry(width,.12,horizontal/steps+.025)
        const stair=new THREE.InstancedMesh(geometry,material(0xb5b5a6),steps)
        const transform=new THREE.Object3D()
        for(let i=0;i<steps;i++) { transform.position.copy(a).lerp(b,(i+.5)/steps);transform.position.y-=.06;transform.rotation.y=yaw;transform.updateMatrix();stair.setMatrixAt(i,transform.matrix) }
        stair.receiveShadow=true;indoorGeometry.add(stair)
      } else {
        const deck=new THREE.Mesh(new THREE.BoxGeometry(width,.12,horizontal),material(edge.kind==='room'?0xb6aa92:0xaaa99b))
        deck.position.copy(a).lerp(b,.5);deck.position.y-=.07;deck.rotation.y=yaw;deck.receiveShadow=true;indoorGeometry.add(deck)
      }
      if(edge.kind==='stairs')for(const side of [-1,1]) {
        const offset=new THREE.Vector3(Math.cos(yaw)*width*.48,.9,-Math.sin(yaw)*width*.48).multiply(new THREE.Vector3(side,1,side))
        const rail=new THREE.Mesh(new THREE.CylinderGeometry(.025,.025,a.distanceTo(b),8),material(0x677c73,.4))
        rail.position.copy(a).lerp(b,.5).add(offset);rail.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),b.clone().sub(a).normalize());indoorGeometry.add(rail)
        for(let i=0;i<=4;i++){const post=new THREE.Mesh(new THREE.CylinderGeometry(.022,.022,.9,6),material(0x677c73,.4));post.position.copy(a).lerp(b,i/4).add(offset);post.position.y-=.45;indoorGeometry.add(post)}
      }
    }
    const color=edge.kind==='stairs'?0x599fea:edge.kind==='assembly'?0x80d6a6:0x67aa9c
    const rail=new THREE.Mesh(new THREE.CylinderGeometry(.055,.055,a.distanceTo(b),6),material(color))
    rail.position.copy(a).lerp(b,.5);rail.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),b.clone().sub(a).normalize());indoorGeometry.add(rail)
    if(edge.kind==='stairs') {
      const heatMaterial = new THREE.MeshBasicMaterial({ color: 0x54d4a4, transparent: true, opacity: .2, depthWrite: false, blending: THREE.AdditiveBlending })
      const heat = new THREE.Mesh(new THREE.CylinderGeometry(Math.max(.28, edge.width_meters * .3), Math.max(.28, edge.width_meters * .3), a.distanceTo(b), 8, 1, true), heatMaterial)
      heat.position.copy(a).lerp(b,.5); heat.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),b.clone().sub(a).normalize()); heat.userData.density = 0; indoorGeometry.add(heat); stairHeatMeshes.set(edge.id, heat)
    }
    const node=graph.nodes.find(n=>n.x===edge.start.x&&n.y===edge.start.y&&n.height===edge.start.height)
    for(const child of indoorGeometry.children.slice(firstChild))child.userData.slice={buildingId:node?.building_id,low:Math.min(edge.start.height,edge.end.height),high:Math.max(edge.start.height,edge.end.height)}
  }
  for (const node of assemblyNodes.value) {
    const marker=createAssemblyPoint(node.name)
    marker.group.position.copy(worldPoint(node.x,node.y,node.height))
    scene.add(marker.group); assemblyModels.set(node.id,marker)
    register(marker.group,{title:node.name,type:'集合点',detail:'以服务端到达和清点记录为准；选派路线不等于已经到达。',x:node.x,y:node.y})
  }
  for(const n of graph.nodes.filter(n=>n.kind==='corridor')) {
    const disk=new THREE.Mesh(new THREE.CircleGeometry(n.kind==='assembly'?1.7:.45,24),new THREE.MeshBasicMaterial({color:n.kind==='assembly'?0x8fe8ae:0x74a9c5,side:THREE.DoubleSide,transparent:true,opacity:.7}))
    disk.rotation.x=-Math.PI/2;disk.position.copy(worldPoint(n.x,n.y,n.height));disk.position.y+=.04;disk.userData.slice={buildingId:n.building_id,low:n.height,high:n.height};indoorGeometry.add(disk)
    if(n.kind==='assembly')register(disk,{title:n.name,type:'集合点',detail:'人员必须沿集合通道到达后才能清点。',x:n.x,y:n.y})
  }
}
function showIndoor(): void {
  if(indoorView.value){toggleIndoor(false);return}
  const person=activeResident.value
  focusIndoorFloor(person?.current_floor ? Math.max(1,Math.ceil(person.current_floor)) : person?.floor ?? props.simulation?.world?.parameters?.fire_floor ?? 1,
    person?.building_id || visibleIndoorBuilding.value || props.simulation?.environment.indoor?.building_id || indoorBuildings.value[0]?.id)
}
function toggleIndoor(silent:boolean): void {
  indoorView.value = !indoorView.value
  if(indoorGeometry) indoorGeometry.visible=indoorView.value
  const person = activeResident.value ?? props.simulation?.residents.find(p => p.floor)
  const home = props.simulation?.world?.objects.find(o => o.id === person?.building_id)
  const occupiedBuildings = new Set(props.simulation?.residents.map(p=>p.building_id))
  for(const child of scene.children) if(child.userData.buildingLabel) child.visible=true
  for (const [id, object] of buildingMeshes) {
    object.visible=true
    object.traverse(child => {
    const mesh = child as THREE.Mesh
    const materials = Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : []
    for (const mat of materials) { mat.transparent = indoorView.value && occupiedBuildings.has(id); mat.opacity = mat.transparent ? .13 : 1; mat.depthWrite = !mat.transparent; mat.needsUpdate = true }
    })
  }
  if (home) {
    viewMode.value = 'director'; targetLookAt.set(home.x - 50, home.floors * 1.5, home.y - 50)
    targetCameraPosition.copy(targetLookAt).add(new THREE.Vector3(20, 10, 26)); controls.enabled = true
  }
  if(!indoorView.value)for(const child of indoorGeometry.children){child.visible=true;child.userData.sliceVisible=true}
  updateEntities()
  if(!silent)flashNotice(indoorView.value ? '楼内示意剖面：人物按服务端三维通道位置行走，不是真实户型或实测楼梯' : '已恢复建筑外观')
}
function focusIndoorFloor(floor:number,buildingId?:string):void {
  const id=buildingId||props.simulation?.environment.indoor?.building_id||visibleIndoorBuilding.value||indoorBuildings.value[0]?.id
  const building=props.simulation?.world?.objects.find(object=>object.id===id)
  if(!building)return
  floor=Math.max(1,Math.min(building.floors,Math.round(floor)))
  visibleIndoorFloor.value=floor;visibleIndoorBuilding.value=building.id
  if(!scene)return
  if(!indoorView.value)toggleIndoor(true)
  viewMode.value='director';controls.enabled=true
  for(const [modelId,model] of buildingMeshes)model.visible=modelId!==building.id
  targetLookAt.copy(worldPoint(building.x,building.y,floorHeight(floor)))
  targetCameraPosition.copy(targetLookAt).add(indoorCameraOffset(building.width,building.depth,camera.aspect))
  for(const child of indoorGeometry.children){
    const slice=child.userData.slice
    child.userData.sliceVisible=Boolean(slice&&slice.buildingId===building.id&&slice.high<=floorHeight(floor)+.01&&slice.high>=floorHeight(floor)-.01)
    child.visible=child.userData.sliceVisible
  }
  updateEntities();emit('indoorFocus',{buildingId:building.id,floor});renderDirty=true
}
function indoorActorVisible(person:{height?:number;building_id?:string;x:number;y:number}):boolean {
  if(!indoorView.value)return (person.height??0)===0
  if(!visibleIndoorFloor.value)return true
  if(person.building_id&&person.building_id!==visibleIndoorBuilding.value)return (person.height??0)===0
  if(!person.building_id&&(person.height??0)>0){
    const home=indoorBuildings.value.find(b=>b.id===visibleIndoorBuilding.value)
    if(home&&(Math.abs(person.x-home.x)>home.width/2+1||Math.abs(person.y-home.y)>home.depth/2+1))return false
  }
  const height=person.height??0, level=floorHeight(visibleIndoorFloor.value)
  return height===0||floorContainsHeight(height,level,visibleIndoorFloor.value===1?0:floorHeight(visibleIndoorFloor.value-1)+.06)
}
function focusPoint(x: number, y: number): void {
  viewMode.value = 'director'; controls.enabled = true
  targetLookAt.copy(worldPoint(x, y)); targetCameraPosition.copy(targetLookAt).add(new THREE.Vector3(15, 28, 26)); renderDirty = true
}
function focusResident(id: string): void {
  const person = props.simulation?.residents.find(p => p.id === id)
  if (!person) return
  if (viewMode.value === 'resident' && selectedResident.value === id) {
    selected.value = { title: person.label, type: person.vulnerable ? '重点关照人员' : '参演居民智能体', detail: person.behavior ?? '等待指令', residentId: person.id, x: person.x, y: person.y }
    return
  }
  if (person?.indoor_stage && person.indoor_stage !== 'outdoor') focusIndoorFloor(Math.max(1,Math.ceil(person.current_floor??person.floor??1)),person.building_id)
  selectAccessibleObject({ target: { value: id } } as unknown as Event)
}
function pointRobotAtSelection(): void {
  if (!props.interactive || selected.value?.x === undefined || selected.value?.y === undefined) return
  const object = props.simulation?.world?.objects.find(o => o.name === selected.value?.title)
  emit('previewAction', { kind: 'robot', x: object?.entry.x ?? selected.value.x, y: object?.entry.y ?? selected.value.y, target: selected.value.title })
}
function selectResidents(ids: string[]): void { selectedResidents.value=ids; toolMode.value='residents'; if(controls)controls.enabled=false; if(ids.some(id=>props.simulation?.residents.find(p=>p.id===id)?.indoor_stage!=='outdoor')&&!indoorView.value)showIndoor(); if(controls)controls.enabled=false; updateEntities() }
function selectCurrentResident(): void {
  const id = selected.value?.residentId ?? activeResident.value?.id
  if (!id) return
  setView('director')
  selectedResidents.value = [id]; toolMode.value = 'residents'; controls.enabled = false
  emit('selection', selectedResidents.value); updateEntities()
}
defineExpose({ focusPoint, focusResident, showIndoor, selectResidents, focusIndoorFloor })

function animate(time = 0): void {
  animationFrame = requestAnimationFrame(animate)
  // Balanced and low quality cap expensive scene updates as well as GPU draws.
  const frameInterval = quality.value === 'low' ? 1000 / 24 : quality.value === 'medium' ? 1000 / 30 : 0
  if (time - lastFrameTime < frameInterval && !renderDirty) return
  const delta = Math.min(.05, Math.max(0, (time-lastFrameTime)/1000)); lastFrameTime=time
  if (!pageVisible) return
  // Reduced motion removes decorative pulses and camera easing, not the drill's
  // essential spatial feedback. Positions still stop at the server's last sample.
  const activelyAnimating = props.status === 'running'
  vehicleVisuals?.step(delta, activelyAnimating, time / 1000, !reducedMotion && props.effectsEnabled !== false)
  rescueVisuals?.step(delta, activelyAnimating, time / 1000, !reducedMotion && props.effectsEnabled !== false)
  if (!activelyAnimating && !renderDirty) return
  const fireScale = .8 + (props.simulation?.fire.intensity ?? 20) / 115
  if(activelyAnimating)visualSeconds+=delta
  const wind = props.simulation?.world?.parameters?.wind_direction ?? '微风'
  fireEffects?.update(reducedMotion ? 0 : visualSeconds, showFireSource.value ? props.simulation?.fire.intensity ?? 0 : 0, props.simulation?.fire.smoke_radius ?? 8, wind, camera, qualityFactor,Boolean(props.simulation?.environment.indoor))
  if(fireLight)fireLight.visible=showFireSource.value
  if(fireCore)fireCore.visible=showFireSource.value
  for(const mesh of [...residentMeshes.values(),...helperMeshes.values()]) {
    const distance = actorMotion.step(mesh, delta, activelyAnimating)
    mesh.userData.frameDistance = distance; mesh.userData.moved = distance > .00001
    const moving=activelyAnimating && distance > .00001
    if (crowdRenderer && residentMeshes.has(mesh.name)) continue
    if (!actorAssets.updatePerson(mesh, delta, distance, activelyAnimating, camera)) {
      posePerson(mesh,moving,visualSeconds,Boolean(mesh.userData.exposed),Boolean(mesh.userData.crowded))
    }
  }
  crowdRenderer?.update(camera, new Set([...selectedResidents.value, activeResident.value?.id ?? '']), quality.value === 'high' ? 24 : quality.value === 'medium' ? 12 : 6, time / 1000, activelyAnimating,
    (model, actor) => { if (!actorAssets.updatePerson(model, delta, actor.userData.frameDistance ?? 0, activelyAnimating, camera)) posePerson(model, actor.userData.moved, visualSeconds, actor.userData.exposed, actor.userData.crowded) })
  if(robotGroup?.userData.targetPosition) {
    const distance=actorMotion.step(robotGroup, delta, activelyAnimating)
    for(const wheel of robotGroup.userData.wheels as THREE.Mesh[])wheel.rotation.x-=distance/.23
    actorAssets.updateRobot(robotGroup, delta, distance, props.robot?.state ?? 'idle', activelyAnimating, visualSeconds, props.robot?.battery ?? 0)
  }
  if (fireLight) fireLight.intensity = (props.simulation?.fire.intensity ?? 0) <= 0 ? 0 : props.effectsEnabled === false ? 2.4 : 5.5 + (reducedMotion ? 0 : Math.sin(time * .011) * 1.3) + fireScale * 2
  if (roadHeatMesh) (roadHeatMesh.material as THREE.MeshBasicMaterial).opacity = .32 + (reducedMotion ? 0 : Math.sin(time * .0024) * .08)
  for (const heat of stairHeatMeshes.values()) {
    const density = Number(heat.userData.density ?? 0)
    const heatMaterial = heat.material as THREE.MeshBasicMaterial
    heatMaterial.opacity = .14 + density * .006 + (reducedMotion ? 0 : Math.sin(time * .004 + density) * .06)
    const pulse = 1 + (reducedMotion ? 0 : Math.sin(time * .004 + density) * density * .0016)
    heat.scale.set(pulse, 1, pulse)
  }
  for (const helper of helperMeshes.values()) {
    const pulse = helper.userData.meetingPulse as THREE.Mesh | undefined
    if (!pulse?.visible) continue
    const phase = reducedMotion ? 1 : 1 + Math.sin(time * .006) * .22
    pulse.scale.setScalar(phase); (pulse.material as THREE.MeshBasicMaterial).opacity = .75 - (phase - 1) * 1.3
  }
  updateCameraFollow()
  if (!userOrbiting) {
    if (reducedMotion || viewMode.value==='resident') { camera.position.copy(targetCameraPosition); controls.target.copy(targetLookAt) }
    else { camera.position.lerp(targetCameraPosition, .045); controls.target.lerp(targetLookAt, .055) }
  }
  controls.update()
  for(const child of scene.children)if(child instanceof THREE.Sprite && child.userData.buildingLabel) {
    const distance=child.position.distanceTo(camera.position)
    const width=Math.min(7,Math.max(2,distance*.09));child.scale.set(width,width*72/384,1)
    child.visible=viewMode.value!=='resident' && distance>12 && !indoorView.value
  }
  renderer.render(scene, camera)
  frameCount++
  if(time-sampleStarted>=1000) { fps.value=activelyAnimating?Math.round(frameCount*1000/(time-sampleStarted)):0;frameCount=0;sampleStarted=time }
  const cameraSettled = camera.position.distanceTo(targetCameraPosition) < .08 && controls.target.distanceTo(targetLookAt) < .08
  renderDirty = !activelyAnimating && !reducedMotion && !cameraSettled
}

function updateCameraFollow(): void {
  if (viewMode.value === 'robot' && robotGroup) {
    const offset = new THREE.Vector3(2.8, 2.3, 4.4).applyAxisAngle(new THREE.Vector3(0, 1, 0), robotGroup.rotation.y)
    targetCameraPosition.copy(robotGroup.position).add(offset)
    targetLookAt.copy(robotGroup.position).add(new THREE.Vector3(0, .65, 0))
  }
  if (viewMode.value === 'resident' && activeResident.value) {
    const mesh = residentMeshes.get(activeResident.value.id)
    if (mesh) {
      // Follow the rendered actor's route tangent at corridor corners. A vector
      // towards the next snapshot cuts diagonally across turns and walls.
      const heading = new THREE.Vector3(0, 0, -1).applyQuaternion(mesh.quaternion)
      if (heading.lengthSq() < .01) heading.set(0, 0, -1)
      heading.y = 0; heading.normalize()
      targetCameraPosition.copy(mesh.position).add(new THREE.Vector3(0, 1.6, 0)).addScaledVector(heading, .18)
      targetLookAt.copy(targetCameraPosition).addScaledVector(heading, 9); targetLookAt.y += .08
    }
  }
}

function updateResidentTrail(resident: Resident, position: THREE.Vector3): void {
  const points = residentTrails.get(resident.id) ?? []
  const last = points[points.length - 1]
  if (!last || last.distanceToSquared(position) > .04) {
    points.push(position.clone().add(new THREE.Vector3(0, .08, 0)))
    if (points.length > (qualityFactor === 1 ? 42 : 24)) points.shift()
    residentTrails.set(resident.id, points)
  }
  const shouldShow = resident.id === activeResident.value?.id || selectedResidents.value.includes(resident.id) || (resident.smoke_exposure ?? 0) > 5
  let line = residentTrailLines.get(resident.id)
  if (points.length > 1 && !line) {
    line = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: 0x67dfcf, transparent: true, opacity: .78, depthWrite: false }))
    residentTrailLayer.add(line); residentTrailLines.set(resident.id, line)
  }
  if (!line) return
  if (last !== points[points.length - 1]) { line.geometry.dispose(); line.geometry = new THREE.BufferGeometry().setFromPoints(points) }
  const trailMaterial = line.material as THREE.LineBasicMaterial
  trailMaterial.color.setHex((resident.smoke_exposure ?? 0) > 5 ? 0xff6248 : resident.assisted ? 0x6aa9ff : 0x67dfcf)
  trailMaterial.opacity = shouldShow ? .88 : .16
  line.visible = resident.status !== 'waiting' || shouldShow
}

function updateHelperLink(helper: NonNullable<Simulation['helpers']>[number], helperMesh: THREE.Group): void {
  const id = helperIdentity(helper)
  const points = meetingRoute(helper)
  const selectedTarget = helper.resident_id === selected.value?.residentId || helper.resident_id === selectedResident.value || selectedResidents.value.includes(helper.resident_id ?? '')
  const visible = selectedTarget && points.length > 1 && (indoorView.value || points.every(point => (point.height ?? 0) === 0))
  let line = helperLinkLines.get(id)
  if (!line && visible) {
    line = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineDashedMaterial({ color: 0x72b4ff, dashSize: .45, gapSize: .28, transparent: true, opacity: .78 }))
    helperLinkLayer.add(line); helperLinkLines.set(id, line)
  }
  if (line) line.visible = visible
  if (line && visible) {
    const signature = JSON.stringify(points)
    if (signature !== line.userData.signature) {
      line.geometry.dispose()
      line.geometry = new THREE.BufferGeometry().setFromPoints(points.map(point => worldPoint(point.x, point.y, point.height).add(new THREE.Vector3(0, .12, 0))))
      line.computeLineDistances(); line.userData.signature = signature
    }
  }
  const pulse = helperMesh.userData.meetingPulse as THREE.Mesh | undefined
  if (pulse) pulse.visible = helper.state === 'escorting'
}

function updateStairHeat(): void {
  for (const [edgeId, heat] of stairHeatMeshes) {
    const edge = props.simulation?.spatial_network?.edges.find((item) => item.id === edgeId)
    const density = edge?.density_percent ?? 0
    heat.userData.density = density
    const color = new THREE.Color(density > 70 ? 0xff4935 : density > 35 ? 0xffb43d : 0x54d4a4)
    ;(heat.material as THREE.MeshBasicMaterial).color.copy(color)
    heat.visible = density > 0 && heat.userData.sliceVisible !== false
  }
}

function updateEntities(): void {
  if (scene && props.simulation?.world) {
    const anchor = props.simulation.world.fire_source?.ignition_position
    const origin = anchor ?? props.simulation.world.fire_origin
    if (fireEffects) {
      fireEffects.group.position.copy(worldPoint(origin.x, origin.y, origin.height))
      fireEffects.group.scale.setScalar(props.simulation.environment.indoor ? .32 : 1)
      // Historical scenes retain their original room-centre flame offset.
      if (props.simulation.environment.indoor && !anchor) fireEffects.group.position.y += .8
      fireEffects.group.visible = showFireSource.value
    }
    if (fireLight) fireLight.position.copy(worldPoint(origin.x, origin.y,origin.height)).add(new THREE.Vector3(0,2,0))
    if(indoorFireVisuals&&props.simulation.environment.indoor){indoorFireVisuals.group.visible=indoorView.value&&visibleIndoorBuilding.value===props.simulation.environment.indoor.building_id;if(indoorFireVisuals.group.visible)indoorFireVisuals.update(props.simulation.environment.indoor,visibleIndoorFloor.value)}
    if (fireCore) {
      fireCore.position.copy(worldPoint(origin.x, origin.y,origin.height)).add(new THREE.Vector3(0,1.5,0))
      fireCore.userData.selection.objectId = props.simulation.world.fire_source?.location.object_id ?? props.simulation.world.objects.find(object => object.type === 'charging_shed' && object.x === origin.x && object.y === origin.y)?.id
    }
    for (const [id, marker] of fireSourceMarkers) {
      marker.visible = Boolean(props.fireSourceSelection?.enabled && props.fireSourceSelection.eligibleIds.includes(id))
      marker.material.color.setHex(id === props.fireSourceSelection?.selectedId ? 0xffca70 : 0x95e5c6)
    }
  }
  if (scene && props.simulation) {
    if (!vehicleVisuals) { vehicleVisuals = new VehicleVisuals(object => interactiveMeshes.push(object), () => { renderDirty = true }); scene.add(vehicleVisuals.layer) }
    vehicleVisuals.update(props.simulation.vehicles ?? [], props.elapsedSeconds, props.status === 'running')
    if (!rescueVisuals) { rescueVisuals = new RescueVisuals(object => interactiveMeshes.push(object)); scene.add(rescueVisuals.layer) }
    rescueVisuals.update(props.simulation.vehicles ?? [], props.simulation.residents, props.elapsedSeconds, props.status === 'running')
    if (selected.value?.vehicleId) {
      const vehicle = props.simulation.vehicles?.find(item => item.id === selected.value?.vehicleId)
      if (vehicle) Object.assign(selected.value, { x: vehicle.x, y: vehicle.y, detail: vehicle.service ? `${vehicle.service.label} · 剩余 ${vehicle.service.remaining_seconds} 秒。${vehicle.service.reason}` : `${vehicle.reason}${vehicle.passenger ? ` 车内人员：${vehicle.passenger.label}。` : ''}${vehicle.remaining_seconds === null ? '' : ` 剩余 ${vehicle.remaining_seconds} 秒。`}` })
    }
  }
  if (!scene || destroyed) return
  // Refresh click-time details and assistant context from each authoritative snapshot.
  const focus = selected.value
  if (focus?.residentId) {
    const person = props.simulation?.residents.find(item => item.id === focus.residentId)
    if (person) {
      const destination = person.exit === 'north' ? '北侧集合点' : person.exit === 'south' ? '南侧集合点' : '尚未分配出口'
      focus.x = person.x; focus.y = person.y
      focus.detail = `${person.last_location ?? '现场定位中'} · ${person.behavior ?? person.status} · ${destination} · 累计排队 ${Math.round(person.queue_seconds ?? 0)} 秒 · 烟气暴露 ${(person.smoke_exposure ?? 0).toFixed(1)}`
    } else selected.value = null
  } else if (focus?.action === 'robot' && props.robot) {
    focus.x = props.robot.x; focus.y = props.robot.y; focus.detail = props.robot.reason
  }
  if (props.elapsedSeconds < lastEntitySeconds) {
    // A replay seek starts a new visible history; never draw trails from the future.
    actorMotion.clear(); residentTrails.clear(); residentTrailLines.clear()
    disposeLayer(residentTrailLayer)
  }
  lastEntitySeconds = props.elapsedSeconds
  for (const [id, marker] of assemblyModels) marker.update(assemblyAttendance(assemblyPeople.value,id))
  for (const exit of exitModels) {
    const node=props.simulation?.road_network?.nodes.find(item=>item.id===exit.nodeId)
    const edges=node ? props.simulation?.road_network?.edges.filter(edge=>[edge.start,edge.end].some(point=>Math.hypot(point.x-node.x,point.y-node.y)<.01)) ?? [] : []
    const blocked=edges.length>0 && edges.every(edge=>edge.status==='blocked')
    const restricted=edges.some(edge=>edge.status!=='open')
    const color=!edges.length ? 0x879790 : blocked ? 0xd9654e : restricted ? 0xd4a957 : 0x70a393
    exit.materials.forEach(item=>item.color.setHex(color))
    const detail=!edges.length ? '尚未关联道路节点，请在场景配置中检查出口接入。' : `出口接入${blocked?'已封锁':restricted?'部分受限':'畅通'} · 相邻道路排队 ${edges.reduce((sum,edge)=>sum+(edge.waiting_count??0),0)} 人。完整路线风险请以指派前预演为准。`
    exit.group.userData.selection.detail=detail
    if(selected.value?.title===exit.group.userData.selection.title && selected.value?.type==='安全出口') selected.value.detail=detail
  }
  for (const hydrant of hydrantModels) {
    const failed = hydrant.isEast && props.simulation?.environment.east_hydrant === 'failed'
    hydrant.warning.visible = failed
    hydrant.paint.forEach(m=>m.color.setHex(failed ? 0x5b625e : m.userData.originalColor))
    const selection = hydrant.group.userData.selection
    if(selection) {
      selection.detail=failed ? '水源异常 · 不可用；安排物业复核并选择备用水源' : '消防水源可用 · 以本场服务端资源状态为准'
      const focused = selected.value
      if (focused && focused.title === selection.title && focused.type === '消防水源') focused.detail = selection.detail
    }
  }
  const hour=Number.parseInt(props.simulation?.world?.parameters?.start_time?.split(':')[0] ?? '20',10)
  const night=hour>=18 || hour<6
  if (ambientLight) ambientLight.intensity = props.highContrast ? 3.2 : night ? 1.5 : 2.8
  if (scene.fog instanceof THREE.FogExp2) scene.fog.density = props.highContrast ? .001 : night ? .0035 : .0015
  ;(groundPlane.material as THREE.MeshStandardMaterial).color.setHex(night ? 0x647066 : 0xaaa995)
  for (const helper of displayedHelpers.value) {
    const id = helperIdentity(helper)
    let mesh = helperMeshes.get(id)
    if (!mesh) {
      mesh = createPerson(id, false, true)
      const meetingPulse = new THREE.Mesh(new THREE.RingGeometry(.62, .82, 24), new THREE.MeshBasicMaterial({ color: 0x74b7ff, transparent: true, opacity: .75, side: THREE.DoubleSide, depthWrite: false })); meetingPulse.rotation.x = -Math.PI / 2; meetingPulse.position.y = .06; meetingPulse.visible = false; mesh.add(meetingPulse); mesh.userData.meetingPulse = meetingPulse
      scene.add(mesh); helperMeshes.set(id, mesh); interactiveMeshes.push(mesh)
      void actorAssets.person(mesh, id, false, true)
    }
    const presentation = helperPresentation(helper)
    const staffSelection:SelectedObject = {title:helper.staff_name??'护送员',type:'值守资源',residentId:helper.resident_id,x:helper.x,y:helper.y,
      detail:[helper.responsible,presentation.label,helper.behavior].filter(Boolean).join(' · ')}
    mesh.traverse(child=>{child.userData.selection=staffSelection})
    if (selected.value?.type==='值守资源' && selected.value.title===staffSelection.title) selected.value=staffSelection
    const staffRing=(mesh.userData.ring as THREE.Mesh|undefined)?.material as THREE.MeshBasicMaterial|undefined
    if(staffRing){staffRing.color.setHex(presentation.color);staffRing.opacity=helper.state==='completed'?.4:.8}
    const next=worldPoint(helper.x, helper.y, helper.height ?? 0)
    const route = (helper.route_points ?? []).map(point => worldPoint(point.x, point.y, point.height))
    actorMotion.accept(mesh, next, route, props.elapsedSeconds, props.status === 'running')
    mesh.userData.behaviorState = helper.state
    mesh.userData.crowded = (helper.congestion ?? 0) > 55
    mesh.userData.targetPosition=next;mesh.visible = indoorActorVisible(helper)
  }
  const visibleStaff = new Set(displayedHelpers.value.map(helperIdentity))
  for (const [id, mesh] of helperMeshes) if (!visibleStaff.has(id)) mesh.visible = false
  for (const [id, line] of helperLinkLines) if (!visibleStaff.has(id)) line.visible = false
  if (robotGroup) robotGroup.visible = Boolean(props.robot)
  if (!props.robot && selected.value?.action === 'robot') selected.value = null
  if (props.robot && robotGroup) {
    const next=worldPoint(props.robot.x, props.robot.y)
    const taskRoute = currentRobotTask.value?.route_points ?? props.robot.task_queue?.filter(task => task.status === 'completed').slice(-1)[0]?.route_points ?? []
    actorMotion.accept(robotGroup, next, taskRoute.map(p => worldPoint(p.x, p.y, p.height)), props.elapsedSeconds, props.status === 'running')
    robotGroup.userData.targetPosition=next
    if(robotGroup.userData.scan)robotGroup.userData.scan.visible=['sensing','inspecting','scanning','verifying'].includes(props.robot.state)
    rebuildRoute()
  }
  for (const resident of props.simulation?.residents ?? []) {
    const mesh = residentMeshes.get(resident.id)
    if (mesh) {
      const nextPosition=worldPoint(resident.x, resident.y, resident.height ?? 0)
      actorMotion.accept(mesh, nextPosition, (resident.route_points ?? []).map(p => worldPoint(p.x, p.y, p.height)), props.elapsedSeconds, props.status === 'running')
      mesh.userData.targetPosition=nextPosition; mesh.visible = indoorView.value || !resident.indoor_stage || resident.indoor_stage === 'outdoor'
      const ringMaterial = (mesh.userData.ring as THREE.Mesh | undefined)?.material as THREE.MeshBasicMaterial | undefined
      const danger = (resident.smoke_exposure ?? 0) > 5
      const crowded = (resident.congestion ?? 0) > 55
      mesh.userData.exposed=danger;mesh.userData.crowded=crowded
      mesh.userData.behaviorState = resident.status
      mesh.userData.assisted = resident.assisted
      if (ringMaterial) { ringMaterial.color.setHex(selectedResidents.value.includes(resident.id) ? 0xffffff : danger ? 0xff4d2e : crowded ? 0xffc45d : resident.vulnerable ? 0xf3be62 : 0x8ed0c2); ringMaterial.opacity = selectedResidents.value.includes(resident.id) ? 1 : .75 }
      mesh.scale.setScalar(1)
      if (indoorView.value && resident.height === undefined && resident.indoor_stage && resident.indoor_stage !== 'outdoor') {
        const home = props.simulation?.world?.objects.find(o => o.id === resident.building_id)
        if (home) {
          const index = Number(resident.id.split('-').pop()) - 1
          const onStairs = ['stairs','exit_queue'].includes(resident.indoor_stage)
          mesh.position.set(home.x - 50 + (onStairs ? home.width * .38 : ((index % 5) - 2) * home.width / 6), Math.max(.18, ((resident.current_floor ?? resident.floor ?? 1) - 1) * 3.2+.18), home.y - 50 + ((Math.floor(index / 5) % 2) - .5) * home.depth * .6)
          mesh.userData.targetPosition=mesh.position.clone(); mesh.visible = true
        }
      }
      mesh.visible = mesh.visible && !(viewMode.value === 'resident' && activeResident.value?.id === resident.id)
      mesh.visible = mesh.visible && !['loading', 'onboard', 'handing_over'].includes(resident.medical_transfer?.phase ?? '')
      if(indoorView.value)mesh.visible=mesh.visible&&indoorActorVisible(resident)
      updateResidentTrail(resident, mesh.position)
    }
  }
  for (const helper of displayedHelpers.value) {
    const mesh = helperMeshes.get(helperIdentity(helper))
    if (mesh) updateHelperLink(helper, mesh)
  }
  updateStairHeat()
  rebuildBlockages()
  rebuildRoadNetwork()
  rebuildResidentRoutes()
  renderDirty = true
}

function rebuildBlockages(): void {
  if (!blockageLayer) return
  const signature = JSON.stringify((props.simulation?.environment.blockages ?? []).map(b=>[b.x,b.y,b.target,b.road_edge_id,props.simulation?.road_network?.edges.find(e=>e.id===b.road_edge_id)?.width_meters]))
  if(signature===blockageSignature)return
  blockageSignature=signature
  for (const child of [...blockageLayer.children]) {
    blockageLayer.remove(child)
    child.traverse((object) => {
      const mesh = object as THREE.Mesh; mesh.geometry?.dispose()
      const materials = Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : []
      materials.forEach((item) => item.dispose())
    })
  }
  for (const blockage of props.simulation?.environment.blockages ?? []) {
    const edge=props.simulation?.road_network?.edges.find(e=>e.id===blockage.road_edge_id || !blockage.road_edge_id && e.name===blockage.target)
    const group = createRoadBarrier(edge?.width_meters ?? 4)
    if(edge)group.rotation.y=Math.atan2(edge.end.x-edge.start.x,edge.end.y-edge.start.y)
    group.position.copy(worldPoint(blockage.x, blockage.y)); blockageLayer.add(group)
  }
}

function disposeLayer(layer: THREE.Group): void {
  for (const child of [...layer.children]) {
    layer.remove(child)
    child.traverse((object) => {
      const mesh = object as THREE.Mesh
      mesh.geometry?.dispose()
      const materials = Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : []
      materials.forEach((item) => item.dispose())
    })
  }
}

function rebuildRoadNetwork(): void {
  if (!roadNetworkLayer) return
  const edges = props.simulation?.road_network?.edges ?? []
  const rebuilt = roadVisuals.update(edges, edge => roadDetail(edge as RoadEdgeState))
  roadHeatMesh = roadVisuals.heat
  if (rebuilt) {
    interactiveMeshes.splice(0, interactiveMeshes.length, ...interactiveMeshes.filter(object => !roadInteractiveMeshes.has(object)))
    roadInteractiveMeshes.clear()
    for (const mesh of roadVisuals.meshes.values()) { interactiveMeshes.push(mesh); roadInteractiveMeshes.add(mesh) }
  }
  const focused = selected.value?.roadEdgeId && roadVisuals.meshes.get(selected.value.roadEdgeId)
  if (focused) Object.assign(selected.value!, focused.userData.selection)
}

function rebuildResidentRoutes(): void {
  if (!residentRouteLayer) return
  const ids = [...new Set([...(props.routePreview ?? []).map(p => p.id), ...selectedResidents.value, ...(selected.value?.residentId ? [selected.value.residentId] : [])])]
  const routes = ids.map(id => props.routePreview?.find(p => p.id === id) ?? props.simulation?.residents.find(p => p.id === id))
  const signature = JSON.stringify([Boolean(props.routePreview?.length), routes.map(p => [p?.id, p?.exit, p && 'route_kind' in p ? p.route_kind : null, p?.route_points])])
  if (signature === residentRouteSignature) return
  residentRouteSignature = signature
  disposeLayer(residentRouteLayer)
  for (const resident of routes) {
    if (!resident?.route_points || resident.route_points.length < 2) continue
    const points = resident.route_points.map((point) => {const p=worldPoint(point.x, point.y, point.height??0);p.y+=.12;return p})
    const robotPreview = 'route_kind' in resident && resident.route_kind === 'robot'
    residentRouteLayer.add(createRouteGuide(points,props.routePreview?.length ? robotPreview ? 0xd1b0ff : resident.exit === 'north' ? 0x85ddff : 0xffd789 : 0x8fe8da,robotPreview))
  }
}

function rebuildRoute(): void {
  if (!scene) return
  const signature = JSON.stringify([Boolean(props.robotRoutePreview?.length), latestRoutePoints.value])
  if (signature === robotRouteSignature) return
  robotRouteSignature = signature
  if (routeLine) { scene.remove(routeLine); routeLine.geometry.dispose(); (routeLine.material as THREE.Material).dispose() }
  const eventPoints = latestRoutePoints.value.map((point) => {const p=worldPoint(point.x, point.y, point.height??0);p.y+=.18;return p})
  if (eventPoints.length < 2) { routeLine = null; return }
  const geometry = new THREE.BufferGeometry().setFromPoints(eventPoints); const routeMaterial = new THREE.LineDashedMaterial({ color: props.robotRoutePreview?.length ? 0xffd789 : 0x56e2d2, dashSize: 1.4, gapSize: .85, transparent: true, opacity: .9 })
  routeLine = new THREE.Line(geometry, routeMaterial); routeLine.computeLineDistances(); scene.add(routeLine)
}

function setView(mode: typeof viewMode.value): void {
  // Pin the person being followed. Otherwise the moving-person fallback changes
  // targets (or disappears) at arrival, hiding the result of the user's decision.
  if (mode === 'resident') selectedResident.value = activeResident.value?.id ?? props.simulation?.residents[0]?.id ?? ''
  if(mode==='resident' && activeResident.value?.indoor_stage && activeResident.value.indoor_stage!=='outdoor' && !indoorView.value)showIndoor()
  viewMode.value = mode; controls.enabled = mode === 'director'
  if (mode === 'director') { targetCameraPosition.set(66, 76, 74); targetLookAt.set(0, 0, 0) }
  if (mode === 'rescue') { targetCameraPosition.set(-58, 32, 54); targetLookAt.set(4, 0, 0) }
  updateEntities(); renderDirty = true
}

function cycleResident(direction: number): void {
  const residents = props.simulation?.residents ?? []
  if (!residents.length) return
  const current = Math.max(0, residents.findIndex((resident) => resident.id === activeResident.value?.id))
  const next = residents[(current + direction + residents.length) % residents.length]!
  selectedResident.value = next.id; selected.value = { title: next.label, type: next.vulnerable ? '重点关照人员' : '参演居民智能体', detail: next.behavior ?? '等待指令', residentId: next.id, x: next.x, y: next.y }
  updateEntities(); renderDirty = true
}

function onPointerDown(event: PointerEvent): void {
  pointerStart.set(event.clientX, event.clientY)
  if(props.interactive && toolMode.value==='residents' && event.button===0) { renderer.domElement.setPointerCapture(event.pointerId); const r=renderer.domElement.getBoundingClientRect(); marquee.value={left:event.clientX-r.left,top:event.clientY-r.top,width:0,height:0} }
}
function onPointerMove(event: PointerEvent): void {
  if(!marquee.value)return
  const r=renderer.domElement.getBoundingClientRect()
  marquee.value={left:Math.min(pointerStart.x,event.clientX)-r.left,top:Math.min(pointerStart.y,event.clientY)-r.top,width:Math.abs(pointerStart.x-event.clientX),height:Math.abs(pointerStart.y-event.clientY)}
}
function cancelMarquee(): void { marquee.value=null }

function onPointerUp(event: PointerEvent): void {
  if (!renderer || isDraggingEvent.value) return
  const box=marquee.value;marquee.value=null
  if(renderer.domElement.hasPointerCapture(event.pointerId))renderer.domElement.releasePointerCapture(event.pointerId)
  if(box && box.width>6 && box.height>6){
    const rect=renderer.domElement.getBoundingClientRect()
    const ids=[...residentMeshes].filter(([id,mesh])=>{if(!mesh.visible||props.simulation?.residents.find(p=>p.id===id)?.status==='evacuated')return false; const p=mesh.position.clone().project(camera), x=(p.x+1)*rect.width/2,y=(1-p.y)*rect.height/2;return p.z>=-1&&p.z<=1&&x>=box.left&&x<=box.left+box.width&&y>=box.top&&y<=box.top+box.height}).map(([id])=>id)
    selectedResidents.value=ids;emit('selection',ids);updateEntities();flashNotice('已框选 '+ids.length+' 人，点击出口或预览路线');return
  }
  if (pointerStart.distanceTo(new THREE.Vector2(event.clientX, event.clientY)) > 5) return
  const bounds = renderer.domElement.getBoundingClientRect(); pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1; pointer.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1
  raycaster.setFromCamera(pointer, camera)
  const hits = raycaster.intersectObjects(interactiveMeshes, true)
  // Hidden LODs and indoor residents remain registered, but must not steal a click.
  const hit = hits.find(candidate => {
    let object: THREE.Object3D | null = candidate.object
    while (object) { if (!object.visible) return false; object = object.parent }
    return true
  })
  if(props.roomSelection){const room=hit?.object.userData.selection?.fireRoom;if(room)emit('fireRoomPick',room);else flashNotice('请选择当前楼层的厨房台面，或使用右侧房间列表。');return}
  if (props.fireSourceSelection?.enabled) {
    const id = hit?.object.userData.selection?.objectId as string | undefined
    if (id && props.fireSourceSelection.eligibleIds.includes(id)) emit('fireSourcePick', id)
    else flashNotice('请选择高亮的充电棚；楼栋与空地不能设为本案例火源。')
    return
  }
  if (hit?.object.userData.selection?.action === 'indoor-door') { emit('inspectIndoor', hit.object.userData.selection.doorId); return }
  if (hit?.object.userData.selection?.action === 'indoor-device') { emit('inspectDevice', hit.object.userData.selection.deviceId); return }
  if (props.interactive === false) return
   const roadHit = hit?.object.userData.selection?.roadEdgeId ? hit : undefined
  const groundHit = raycaster.intersectObject(groundPlane)[0]
  const selection = (hit?.object.userData.crowd?.selection(hit.instanceId) ?? hit?.object.userData.selection) as typeof selected.value
  const roadSelection = roadHit?.object.userData.selection as typeof selected.value
  const point = groundHit?.point
  const x = point ? Math.max(0, Math.min(100, Number((point.x + 50).toFixed(1)))) : undefined
  const y = point ? Math.max(0, Math.min(100, Number((point.z + 50).toFixed(1)))) : undefined
  if (props.interactive && toolMode.value === 'block') {
    if (!roadSelection?.roadEdgeId) { flashNotice('未选择道路：请点击有颜色高亮的真实道路路段'); return }
    selected.value = roadSelection
    emit('previewAction', { kind: 'road', edgeId: roadSelection.roadEdgeId })
    flashNotice(`正在预演封锁 ${roadSelection.title} 后的拥堵与改道`)
    return
  }
  if (props.interactive && toolMode.value === 'robot' && x !== undefined && y !== undefined) {
    const target = selection?.title ?? `空间目标 ${x},${y}`
    selected.value = selection ?? { title: target, type: '机器人空间目标', detail: `坐标 ${x}, ${y}`, x, y }
    emit('previewAction', { kind: 'robot', x, y, target }); flashNotice('正在计算 A* 风险路径，尚未加入任务队列'); return
  }
  if (props.interactive && toolMode.value === 'residents') {
    if(selection && /出口|集合点/.test(selection.type+' '+selection.title) && /北|南/.test(selection.title) && selectedResidents.value.length){ commandSelectedResidents(/北/.test(selection.title)?'north':'south','evacuate');return }
    if (!selection?.residentId) { flashNotice('拖动框选居民，或点击北／南出口预览所选人员路线'); return }
    selectedResident.value = selection.residentId
    selectedResidents.value = selectedResidents.value.includes(selection.residentId) ? selectedResidents.value.filter((id) => id !== selection.residentId) : [...selectedResidents.value, selection.residentId]
    emit('selection', selectedResidents.value); selected.value = selection; updateEntities(); return
  }
  selected.value = selection ?? null
  if (selected.value?.residentId) selectedResident.value = selected.value.residentId
  updateEntities()
}

function flashNotice(message: string): void { interactionNotice.value = message; window.setTimeout(() => { if (interactionNotice.value === message) interactionNotice.value = '' }, 2600) }
function setTool(tool: typeof toolMode.value): void {
  emit('cancelAction')
  toolMode.value = tool
  if (tool !== 'residents') selectedResidents.value = []
  controls.enabled = tool === 'inspect' && viewMode.value === 'director'
  flashNotice({ inspect: '浏览模式：点击对象查看服务端实时状态', block: '封锁工具：请点击有颜色的真实道路路段', robot: '指派工具：点击目标，A* 将按风险和封锁状态规划', residents: '居民工具：连续多选后下达分流或护送指令' }[tool])
  updateEntities()
}
function commandSelectedResidents(exit: 'north' | 'south', action: 'evacuate' | 'priority_assist'): void {
  if (!selectedResidents.value.length) { flashNotice('请先在三维场景中选择至少一名居民'); return }
  emit('previewAction', { kind: 'residents', residentIds: selectedResidents.value, exit, action })
  flashNotice('正在预演所选居民的连续路线、预计用时与拥堵影响')
  updateEntities()
}

function injectDefaultRoadBlock(): void {
  const edges = props.simulation?.road_network?.edges.filter((edge) => edge.status !== 'blocked') ?? []
  const edge = edges.find((item) => /南|消防通道/.test(item.name)) ?? edges[0]
  if (!edge) { flashNotice('当前道路图中没有可封锁路段'); return }
  selected.value = { title: edge.name, type: '真实道路路段', detail: roadDetail(edge), action: 'channel_blocked', roadEdgeId: edge.id, x: (edge.start.x + edge.end.x) / 2, y: (edge.start.y + edge.end.y) / 2 }
  emit('previewAction', { kind: 'road', edgeId: edge.id })
  flashNotice(`正在预演封锁 ${edge.name} 后的拥堵与改道`)
}

function dragEvent(event: DragEvent, eventType: string): void { isDraggingEvent.value = true; event.dataTransfer?.setData('application/x-drill-event', eventType); if (event.dataTransfer) event.dataTransfer.effectAllowed = 'copy' }
function endDrag(): void { isDraggingEvent.value = false }
function dropEvent(event: DragEvent): void {
  isDraggingEvent.value = false
  const type = event.dataTransfer?.getData('application/x-drill-event')
  if (!['channel_blocked', 'hydrant_failure', 'resident_missing'].includes(type ?? '') || !renderer) return
  const bounds = renderer.domElement.getBoundingClientRect(); pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1; pointer.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1; raycaster.setFromCamera(pointer, camera)
  const targetHits = raycaster.intersectObjects(interactiveMeshes, true)
  const targetHit = targetHits[0]
  const roadHit = targetHit?.object.userData.selection?.roadEdgeId ? targetHit : undefined
  const groundHit = raycaster.intersectObject(groundPlane)[0]
  const point = groundHit?.point
  const x = point ? Math.max(0, Math.min(100, point.x + 50)) : undefined
  const y = point ? Math.max(0, Math.min(100, point.z + 50)) : undefined
  const selection = targetHit?.object.userData.selection
  const roadSelection = roadHit?.object.userData.selection
  const target = type === 'channel_blocked' ? roadSelection?.title ?? '' : selection?.title ?? ''
  const valid = type === 'channel_blocked' ? Boolean(roadSelection?.roadEdgeId) : type === 'hydrant_failure' ? /消火栓/.test(target) : /居民|人员|3 号楼/.test(target)
  if (!valid) { interactionNotice.value = '投放位置不匹配：请拖到对应道路、消火栓或居民对象。'; window.setTimeout(() => { interactionNotice.value = '' }, 2600); return }
  if (type === 'channel_blocked' && roadSelection?.roadEdgeId) {
    selected.value = roadSelection
    emit('previewAction', { kind: 'road', edgeId: roadSelection.roadEdgeId })
  } else emit('inject', type as 'hydrant_failure' | 'resident_missing', { x, y, target })
}
function runSelectedAction(): void {
  if (selected.value?.action === 'robot') emit('robotCommand', 'step')
  if (selected.value?.action === 'channel_blocked' && selected.value.roadEdgeId) emit('previewAction', { kind: 'road', edgeId: selected.value.roadEdgeId })
  else if (selected.value?.action && selected.value.action !== 'robot') emit('inject', selected.value.action as 'hydrant_failure', { x: selected.value.x, y: selected.value.y, target: selected.value.title })
}

function selectAccessibleObject(event: Event): void {
  const key = (event.target as HTMLSelectElement).value
  if (!key) { selected.value = null; return }
  setTool('inspect')
  if (!key.startsWith('resident-')) setView('director')
  if (key.startsWith('vehicle:')) {
    const vehicle = props.simulation?.vehicles?.find(v => v.id === key.slice(8))
    if (vehicle) { selected.value = { title: vehicle.name, type: '可调度应急车辆', detail: vehicle.reason, vehicleId: vehicle.id, x: vehicle.x, y: vehicle.y }; focusPoint(vehicle.x, vehicle.y) }
    return
  }
  if (key.startsWith('object:')) {
    const object = props.simulation?.world?.objects.find(o => o.id === key.slice(7))
    if (object) { selected.value = interactiveMeshes.find(mesh=>mesh.userData.selection?.title===object.name)?.userData.selection ?? { title: object.name, type: '社区对象', detail: '与场次冻结地图一致 · 可指派机器人到此接入点', x: object.entry.x, y: object.entry.y }; focusPoint(object.x, object.y) }
    return
  }
  if (key.startsWith('assembly:')) {
    const node=assemblyNodes.value.find(item=>item.id===key)
    if(node) { selected.value={title:node.name,type:'集合点',detail:'到达和清点人数随服务端状态更新；选派路线不等于已经到达。',x:node.x,y:node.y};focusPoint(node.x,node.y) }
    return
  }
  if (key === 'robot') { selected.value = { title: '巡检广播机器人 R-01', type: '具身智能体', detail: props.robot?.reason ?? '等待演练开始', action: 'robot' }; setView('robot'); return }
  if (key === 'building-3') { selected.value = { title: '3 号楼', type: '7 层老旧住宅', detail: '重点疏散楼栋 · 3 名重点人员 · 当前受烟气影响', x: 77, y: 30 }; return }
  if (key === 'east-hydrant') { selected.value = { title: '东侧消火栓', type: '消防水源', detail: '可在演练中注入压力异常', action: 'hydrant_failure', x: 89, y: 47 }; return }
  if (key === 'south-exit') { selected.value = { title: '南门出口', type: '安全出口', detail: '初始通行受限，可注入通道堵塞', action: 'channel_blocked', x: 50, y: 100 }; return }
  if (key.startsWith('road:')) {
    const edge = props.simulation?.road_network?.edges.find((item) => item.id === key.slice(5))
    if (edge) selected.value = { title: edge.name, type: '真实道路路段', detail: roadDetail(edge), action: edge.status === 'blocked' ? undefined : 'channel_blocked', roadEdgeId: edge.id, x: (edge.start.x + edge.end.x) / 2, y: (edge.start.y + edge.end.y) / 2 }
    return
  }
  const resident = props.simulation?.residents.find((item) => item.id === key)
  if (resident) { selectedResident.value = resident.id; selected.value = { title: resident.label, type: resident.vulnerable ? '重点关照人员' : '参演居民智能体', detail: resident.behavior ?? '等待指令', residentId: resident.id, x: resident.x, y: resident.y }; setView('resident') }
}

function onVisibilityChange(): void { pageVisible = !document.hidden; renderDirty = true }
function onSceneKeydown(event: KeyboardEvent): void {
  if (event.target !== event.currentTarget || !camera || !controls) return
  if (event.key === 'Escape') { selected.value = null; emit('cancelAction'); return }
  if (event.key === 'Home') { event.preventDefault(); setView('director'); return }
  if (!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','=','-','_'].includes(event.key)) return
  event.preventDefault()
  const offset = camera.position.clone().sub(controls.target)
  const orbit = new THREE.Spherical().setFromVector3(offset)
  if (event.key === 'ArrowLeft') orbit.theta -= .12
  if (event.key === 'ArrowRight') orbit.theta += .12
  if (event.key === 'ArrowUp') orbit.phi = Math.max(.12, orbit.phi - .08)
  if (event.key === 'ArrowDown') orbit.phi = Math.min(controls.maxPolarAngle, orbit.phi + .08)
  if (['+','='].includes(event.key)) orbit.radius = Math.max(controls.minDistance, orbit.radius * .9)
  if (['-','_'].includes(event.key)) orbit.radius = Math.min(controls.maxDistance, orbit.radius / .9)
  camera.position.copy(controls.target).add(offset.setFromSpherical(orbit))
  targetCameraPosition.copy(camera.position); targetLookAt.copy(controls.target)
  controls.update(); renderDirty = true
}
function updateMotionPreference(): void { reducedMotion = motionPreference.matches || document.documentElement.dataset.reduceMotion === 'true'; renderDirty = true }
const preferenceObserver = new MutationObserver(updateMotionPreference)
let contextRestoreTimer: ReturnType<typeof setTimeout> | undefined
const recoveringContext = ref(false)
function onContextLost(event: Event): void {
  event.preventDefault(); recoveringContext.value = true
  renderError.value = '正在恢复图形连接，演练数据仍由服务端保存。恢复后将显示最新位置。'
  clearTimeout(contextRestoreTimer)
  contextRestoreTimer = setTimeout(() => { if (!destroyed) renderer?.forceContextRestore() }, 350)
}
function onContextRestored(): void { recoveringContext.value = false; renderError.value = ''; resize(); updateEntities(); renderDirty = true }

// Live messages replace the affected state branches; avoid traversing every route
// and frozen model twice for each population tick.
watch(() => [props.robot, props.simulation, props.highContrast, props.status, props.elapsedSeconds], () => { void nextTick(updateEntities) })
watch(() => props.fireSourceSelection, () => updateEntities(), { deep: true })
watch(()=>props.indoorFloor,value=>{if(value!==undefined&&scene)focusIndoorFloor(value)})
let syncingResidentView = false
watch(()=>[viewMode.value,activeResident.value?.id,activeResident.value?.current_floor,activeResident.value?.building_id],()=>{
  const person=activeResident.value
  if(!scene||viewMode.value!=='resident'||!person||person.indoor_stage==='outdoor')return
  const floor=Math.max(1,Math.ceil((person.current_floor??person.floor??1)-.00001))
  if(!indoorView.value||floor!==visibleIndoorFloor.value||person.building_id!==visibleIndoorBuilding.value){
    if (syncingResidentView) return
    syncingResidentView = true
    focusIndoorFloor(floor,person.building_id)
    viewMode.value='resident';controls.enabled=false
    queueMicrotask(() => { syncingResidentView = false })
  }
})
watch(quality,applyQuality)
watch(() => props.elapsedSeconds,value=>{visualSeconds=value;renderDirty=true},{immediate:true})
watch(() => props.events?.[0]?.sequence, () => {
  const event = props.events?.[0]
  if (!event || !scene) return
  directorCue.value = event.message
  const target = event.payload?.x !== undefined && event.payload?.y !== undefined ? worldPoint(event.payload.x, event.payload.y) : null
  if (target && !props.compact && props.cameraEnabled !== false) { targetLookAt.copy(target); targetCameraPosition.copy(target).add(new THREE.Vector3(18, 24, 22)); renderDirty = true }
  window.setTimeout(() => { if (directorCue.value === event.message) directorCue.value = '' }, 4200)
})
onMounted(() => {
  motionPreference.addEventListener('change', updateMotionPreference)
  preferenceObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-reduce-motion'] })
  try { buildScene(); applyQuality() }
  catch { renderError.value = '当前浏览器无法初始化三维渲染，请检查硬件加速设置后重新进入演练中心。' }
})
onBeforeUnmount(() => {
  indoorFireVisuals?.dispose()
  vehicleVisuals?.dispose(); vehicleVisuals = null
  rescueVisuals?.dispose(); rescueVisuals = null
  destroyed = true
  clearTimeout(contextRestoreTimer)
  motionPreference.removeEventListener('change', updateMotionPreference); preferenceObserver.disconnect()
  for (const request of environmentRequests) request.abort()
  environmentRequests.clear(); hydrantModels.length=0
  cancelAnimationFrame(animationFrame); resizeObserver?.disconnect(); document.removeEventListener('visibilitychange', onVisibilityChange)
  if (renderer) { renderer.domElement.removeEventListener('pointerdown', onPointerDown); renderer.domElement.removeEventListener('pointerup', onPointerUp); renderer.domElement.removeEventListener('pointermove', onPointerMove); renderer.domElement.removeEventListener('pointercancel', cancelMarquee); renderer.domElement.removeEventListener('webglcontextlost', onContextLost); renderer.domElement.removeEventListener('webglcontextrestored', onContextRestored) }
  controls?.dispose()
  actorAssets.dispose()
  actorMotion.clear()
  roadVisuals.dispose()
  assemblyModels.clear()
  exitModels.length=0
  scene?.traverse((object) => {
    const mesh = object as THREE.Mesh
    mesh.geometry?.dispose()
    const materials = Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : []
    for (const item of materials) {
      const textured = item as THREE.MeshStandardMaterial
      textured.map?.dispose(); textured.bumpMap?.dispose(); textured.normalMap?.dispose(); textured.roughnessMap?.dispose()
      item.dispose()
    }
  })
  sceneMaterials.dispose()
  renderer?.renderLists.dispose(); renderer?.dispose(); renderer?.forceContextLoss(); renderer?.domElement.remove()
})
watch(() => [props.routePreview, props.robotRoutePreview], () => updateEntities(), { deep: true })
</script>

<style scoped>
.robot-execution { margin-block: 16px; padding-block: 14px; border-block: 1px solid var(--border-default); font-size: 14px; line-height: 1.6; }
.robot-execution__state { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 6px 12px; }
.robot-execution__state strong { font-size: 16px; }
.robot-execution p { margin-block: 10px; overflow-wrap: anywhere; }
.robot-execution progress { display: block; width: 100%; height: 6px; margin-block: 12px; border: 0; appearance: none; accent-color: var(--action-primary); }
.robot-execution progress::-webkit-progress-bar { background: var(--border-default); border-radius: 4px; }
.robot-execution progress::-webkit-progress-value { background: var(--text-primary); border-radius: 4px; }
.robot-execution progress::-moz-progress-bar { background: var(--text-primary); border-radius: 4px; }
@media (max-width: 760px) {
  .twin-stage--object-open .spatial-tool-rack,
  .twin-stage--resident-view .spatial-tool-rack { display: none; }
  .twin-stage--resident-view .resident-pov-hud {
    max-height: calc(100dvh - 230px);
    overflow-y: auto;
    overscroll-behavior: contain;
    box-sizing: border-box;
  }
}
.resident-pov-hud > .resident-escort-feedback {
  margin: 12px 0 0;
  padding-top: 12px;
  border-top: 1px solid rgba(112,153,144,.35);
  color: #c5e4d9;
  font-size: 16px;
  line-height: 1.6;
  white-space: normal;
  overflow-wrap: anywhere;
}
</style>

<template>
  <section class="twin-stage" :class="{ 'twin-stage--compact': compact, 'twin-stage--object-open': inspectorOpen, 'twin-stage--resident-view': viewMode === 'resident' }" :data-status="status">
    <div class="twin-stage__viewport" ref="host" role="application" aria-label="安巷社区三维消防演练沙盘。方向键旋转，加减键缩放，Home 返回鸟瞰；按 Tab 使用对象导航与操作工具。" tabindex="0" @keydown="onSceneKeydown" @dragover.prevent @drop="dropEvent">
      <div v-if="marquee" class="spatial-marquee" :style="{left:marquee.left+'px',top:marquee.top+'px',width:marquee.width+'px',height:marquee.height+'px'}"></div>
      <div v-if="worldLabel" class="twin-world-label"><span>平行世界</span><strong>{{ worldLabel }}</strong></div>
      <div v-if="!compact" class="twin-stage__topline">
        <div class="twin-sensor"><span>火场温度</span><strong>{{ simulation?.sensors.temperature ?? 0 }}<small>℃</small></strong></div>
        <div class="twin-sensor"><span>烟气浓度</span><strong>{{ simulation?.sensors.smoke_ppm ?? 0 }}<small>ppm</small></strong></div>
        <div class="twin-sensor"><span>现场能见度</span><strong>{{ simulation?.environment.visibility ?? 100 }}<small>%</small></strong></div>
        <div class="twin-sensor twin-sensor--clock"><span>演练时刻</span><strong>{{ clockLabel }}</strong></div>
      </div>

      <div v-if="!compact" ref="sceneUtilities" class="scene-utilities" role="group" aria-label="现场显示与车辆工具">
        <label v-if="displayToolsOpen" class="scene-quality">画面品质<select v-model="quality" aria-label="三维画质"><option value="high">精细</option><option value="medium">均衡</option><option value="low">流畅</option></select><small role="status" :title="actorAssetLabel">{{ actorAssetStatus === 'loading' ? '模型加载中' : actorAssetStatus === 'fallback' ? '轻量模型' : status === 'running' && fps ? fps + ' fps' : '静止省电' }}</small></label>
        <button type="button" :disabled="!indoorBuildings.length" :title="indoorBuildings.length ? '显示楼内通道、楼梯与居民位置' : '当前场次没有可观察的室内通道，请检查场景配置或新建连续空间演练'" :aria-pressed="indoorView" @click="showIndoor"><AppIcon name="building" :size="18" />{{ indoorView ? '恢复建筑外观' : '查看楼内透视' }}</button>
        <button v-if="simulation?.environment.indoor" type="button" @click="emit('inspectIndoor')"><AppIcon name="fire" :size="18"/>楼内烟气与门控</button>
        <div v-if="indoorView && indoorBuildings.length" class="scene-floor-controls">
          <select aria-label="观察楼栋" :value="visibleIndoorBuilding" @change="focusIndoorFloor(visibleIndoorFloor??1,($event.target as HTMLSelectElement).value)"><option v-for="building in indoorBuildings" :key="building.id" :value="building.id">{{building.name}}</option></select>
          <select aria-label="透视楼层" :value="visibleIndoorFloor" @change="focusIndoorFloor(Number(($event.target as HTMLSelectElement).value),visibleIndoorBuilding)"><option v-for="floor in indoorFloors" :key="floor" :value="floor">{{floor}} 层</option></select>
        </div>
        <button type="button" :disabled="!simulation?.vehicles?.length" @click="emit('dispatchVehicle', simulation?.vehicles?.[0]?.id ?? '')"><AppIcon name="route" :size="18" />车辆调度</button>
        <button type="button" :aria-expanded="displayToolsOpen" @click="displayToolsOpen=!displayToolsOpen"><AppIcon name="eye" :size="18"/>画面设置</button>
      </div>
      <nav v-if="!compact" class="twin-views" aria-label="沙盘视角">
        <button type="button" title="总控鸟瞰" aria-label="总控鸟瞰" :data-active="viewMode === 'director'" :aria-pressed="viewMode === 'director'" @click="setView('director')"><AppIcon name="eye" />总控鸟瞰</button>
        <button type="button" title="机器人跟随" aria-label="机器人跟随" :data-active="viewMode === 'robot'" :aria-pressed="viewMode === 'robot'" @click="setView('robot')"><AppIcon name="robot" />机器人跟随</button>
        <button type="button" title="居民第一视角" aria-label="居民第一视角" :data-active="viewMode === 'resident'" :aria-pressed="viewMode === 'resident'" @click="setView('resident')"><AppIcon name="person" />居民第一视角</button>
        <button type="button" title="救援视角" aria-label="救援视角" :data-active="viewMode === 'rescue'" :aria-pressed="viewMode === 'rescue'" @click="setView('rescue')"><AppIcon name="rescue" />救援视角</button>
        <button v-if="actorAssetStatus === 'fallback' || retryingModels" type="button" class="twin-model-retry" :disabled="retryingModels" aria-label="重试人物与机器人精细模型" @click="retryActorModels"><AppIcon name="refresh" /><span>{{ retryingModels ? '正在重试模型' : '重试精细模型' }}</span></button>
      </nav>

      <label v-if="!compact && viewMode !== 'resident' && !inspectorOpen" class="twin-object-nav">对象导航<select aria-label="选择沙盘对象" @change="selectAccessibleObject"><option value="">选择建筑、设施或人员</option><option v-for="item in accessibleObjects" :key="item.key" :value="item.key">{{ item.label }}</option></select></label>

      <aside v-if="viewMode === 'resident' && activeResident && !compact" class="resident-pov-hud" aria-live="polite">
        <header><div><span>第一视角跟随</span><strong>{{ activeResident.label }}</strong></div><div class="resident-pov-switch"><button type="button" aria-label="上一位居民" @click="cycleResident(-1)"><AppIcon name="chevron" /></button><button type="button" aria-label="下一位居民" @click="cycleResident(1)"><AppIcon name="chevron" /></button><button type="button" aria-label="返回总控鸟瞰" title="返回总控鸟瞰" @click="setView('director')"><AppIcon name="close" /></button></div></header>
        <p>{{ activeResident.last_location ?? '正在定位连续空间位置' }}</p>
        <div class="resident-pov-grid"><span>当前行为<strong>{{ activeResident.behavior ?? '等待指令' }}</strong></span><span>目标出口<strong>{{ activeResident.exit === 'north' ? '北侧集合点' : activeResident.exit === 'south' ? '南侧集合点' : '未分配' }}</strong></span><span>排队累计<strong>{{ Math.round(activeResident.queue_seconds ?? 0) }} 秒</strong></span><span>护送状态<strong>{{ escortStatusLabel }}</strong></span></div>
        <p v-if="activeHelper?.behavior" role="status" class="resident-escort-feedback">{{ activeHelper.responsible }} · {{ activeHelper.behavior }}</p>
        <div class="resident-pov-exposure"><span>累计烟气暴露<strong>{{ (activeResident.smoke_exposure ?? 0).toFixed(1) }} 规则量</strong></span><i aria-hidden="true"><b :style="{ width: povExposureLevel + '%' }"></b></i></div>
        <button v-if="interactive" class="resident-pov-command" type="button" @click="selectCurrentResident"><AppIcon name="route" :size="17" />指挥此居民</button>
      </aside>

      <div v-if="!compact" class="scene-spatial-controls">
      <nav class="spatial-tool-rack" aria-label="空间直接操作工具">
        <header><span>空间操作</span><small>选工具，再点三维现场</small></header>
        <button type="button" aria-label="观察对象" :aria-pressed="toolMode === 'inspect'" :data-active="toolMode === 'inspect'" @click="setTool('inspect')"><AppIcon name="inspect" /><span>观察对象</span></button>
        <button type="button" aria-label="封锁道路" :aria-pressed="toolMode === 'block'" :data-active="toolMode === 'block'" :disabled="!interactive" @click="setTool('block')"><AppIcon name="block" /><span>封锁道路</span></button>
        <button type="button" aria-label="指派机器人" :aria-pressed="toolMode === 'robot'" :data-active="toolMode === 'robot'" :disabled="!interactive" @click="setTool('robot')"><AppIcon name="robot" /><span>指派机器人</span></button>
        <button type="button" aria-label="选择居民" :aria-pressed="toolMode === 'residents'" :data-active="toolMode === 'residents'" :disabled="!interactive" @click="setTool('residents')"><AppIcon name="users" /><span>选择居民</span></button>
        <p class="spatial-guidance"><AppIcon name="target" /><span>{{ toolHelp }}</span></p>
        <div v-if="toolMode === 'residents'" class="resident-command-inline">
          <header><span>已选 {{ selectedResidents.length }} 人</span><small>点击人物可连续多选</small></header>
          <button type="button" :disabled="!selectedResidents.length" @click="commandSelectedResidents('north', 'evacuate')"><AppIcon name="route" /><span>向北门分流</span></button>
          <button type="button" :disabled="!selectedResidents.length" @click="commandSelectedResidents('south', 'evacuate')"><AppIcon name="route" /><span>向南门分流</span></button>
          <button type="button" :disabled="!selectedResidents.length" @click="commandSelectedResidents('north', 'priority_assist')"><AppIcon name="rescue" /><span>重点人员护送</span></button>
        </div>
        <details class="spatial-event-group">
          <summary><AppIcon name="pulse" /><span>导演事件</span><AppIcon name="chevron" /></summary>
          <small>可点击注入，也可拖到目标位置</small>
          <button type="button" draggable="true" :disabled="!interactive" @dragstart="dragEvent($event, 'channel_blocked')" @dragend="endDrag" @click="injectDefaultRoadBlock"><AppIcon name="block" /><span>通道堵塞</span></button>
          <button type="button" draggable="true" :disabled="!interactive" @dragstart="dragEvent($event, 'hydrant_failure')" @dragend="endDrag" @click="emit('inject', 'hydrant_failure', { x: 89, y: 47, target: '东侧消火栓' })"><AppIcon name="water" /><span>水源失效</span></button>
          <button type="button" draggable="true" :disabled="!interactive" @dragstart="dragEvent($event, 'resident_missing')" @dragend="endDrag" @click="emit('inject', 'resident_missing', { x: 77, y: 30, target: '3 号楼重点人员' })"><AppIcon name="person" /><span>人员失联</span></button>
        </details>
      </nav>
      <div class="scene-spatial-footer">
        <div class="twin-stage__legend">
          <span><i class="legend-dot legend-dot--resident"></i>普通居民</span><span><i class="legend-dot legend-dot--vulnerable"></i>重点人员</span><span><i class="legend-dot legend-dot--danger"></i>暴露轨迹</span><span><i class="legend-dot legend-dot--robot"></i>A* 路线</span><span class="risk-scale"><i></i><small>烟气＋密度综合风险 低</small><small>高</small></span><span v-if="stairCongestion.count" class="stair-density">楼梯通行与排队 {{ stairCongestion.count }} 人 · 密度 {{ stairCongestion.density }}%</span><span>拖动旋转 · 滚轮缩放 · 点击空间直接操作</span>
        </div>
      </div>
      </div>

      <aside v-if="(operationBusy || operationPreview) && !compact" class="spatial-action-preview spatial-action-preview--immersive" data-ui-theme="immersive" aria-label="空间操作预演">
        <header><div><span>{{ operationPreview?.kind === 'road' ? '道路影响预演' : operationPreview?.kind === 'robot' ? '机器人路径预演' : operationPreview?.kind === 'vehicle' ? '车辆到场预演' : '居民疏散预演' }}<template v-if="operationPreview?.expected_sequence !== undefined"> · 现场版本 {{ operationPreview.expected_sequence }}</template></span><strong>{{ operationPreview?.title ?? (operationPreview?.kind === 'residents' ? `${operationPreview.residents?.length ?? 0} 名居民 → ${operationPreview.exit === 'north' ? '北侧' : '南侧'}集合点` : '正在计算空间影响') }}</strong></div><button type="button" aria-label="取消本次预演" @click="emit('cancelAction')"><AppIcon name="close" :size="17" /></button></header>
        <div v-if="operationBusy" class="spatial-action-loading"><i></i><span>正在用当前路网和实时人员状态计算…</span></div>
        <template v-else-if="operationPreview">
          <div class="spatial-action-metrics">
            <div v-if="operationPreview.planned_duration_seconds !== undefined"><span>预计用时</span><strong>{{ operationPreview.planned_duration_seconds ?? '不可达' }}<small v-if="operationPreview.planned_duration_seconds"> 秒</small></strong></div>
            <div v-if="operationPreview.route_distance !== undefined"><span>路线长度</span><strong>{{ operationPreview.route_distance }}<small> 单位</small></strong></div>
            <div v-if="operationPreview.risk_score !== undefined"><span>路径风险</span><strong>{{ operationPreview.risk_score }}</strong></div>
            <div v-if="operationPreview.queue_position !== undefined"><span>队列位置</span><strong>第 {{ operationPreview.queue_position }} 项</strong></div>
            <div v-if="operationPreview.width_meters !== undefined"><span>道路宽度</span><strong>{{ operationPreview.width_meters }}<small> 米</small></strong></div>
            <div v-if="operationPreview.affected_residents !== undefined"><span>需改道居民</span><strong>{{ operationPreview.affected_residents }}<small> 人</small></strong></div>
            <div v-if="operationPreview.affected_robot_tasks !== undefined"><span>受影响任务</span><strong>{{ operationPreview.affected_robot_tasks }}<small> 项</small></strong></div>
          </div>
          <div v-if="operationPreview.impact" class="spatial-impact"><span>确认后 30 秒影响</span><div><p>拥堵人数<strong>{{ operationPreview.impact.congested_before }} → {{ operationPreview.impact.congested_after }}</strong></p><p>烟气暴露<strong>{{ operationPreview.impact.smoke_exposed_before }} → {{ operationPreview.impact.smoke_exposed_after }}</strong></p></div></div>
          <div v-if="operationPreview.score_impact" class="spatial-score-impact"><span>预计过程评分</span><strong>{{ operationPreview.score_impact.before }} → {{ operationPreview.score_impact.after }} <b>({{ operationPreview.score_impact.delta > 0 ? '+' : '' }}{{ operationPreview.score_impact.delta }})</b></strong><small>{{ operationPreview.score_impact.note }}</small></div>
          <p class="spatial-action-note">{{ operationPreview.notice }}</p>
          <p class="spatial-evidence"><AppIcon name="award" :size="15" />{{ operationPreview.kind === 'vehicle' ? operationPreview.rescue_action ? '执行进度与完成结果写入事件证据；喷水效果进入火势、烟气与过程评分计算' : '到场后写入车辆到场证据；调度本身不额外加分' : '确认后将同步写入事件流、过程评分和复盘证据' }}</p>
          <div class="spatial-action-buttons"><button type="button" @click="emit('cancelAction')">重新选择</button><button type="button" :disabled="!operationPreview.can_apply || operationBusy" @click="emit('confirmAction')"><AppIcon name="check" :size="17" />{{ operationPreview.can_apply ? '确认执行' : '当前不可执行' }}</button></div>
        </template>
      </aside>

      <aside v-if="selected && inspectorOpen" class="twin-inspector">
        <button class="twin-inspector__close" type="button" aria-label="关闭对象详情" title="关闭" @click="selected = null"><AppIcon name="close" /></button>
        <span>{{ selected.type }}</span><strong>{{ selected.title }}</strong><p>{{ selected.action === 'robot' ? robot?.reason : selected.detail }}</p>
        <section v-if="selected.action === 'robot' && robot" class="robot-execution" aria-label="机器人实时执行状态">
          <div class="robot-execution__state"><strong>{{ robotStateLabel }}</strong><span>电量 {{ robot.battery }}%</span></div>
          <p v-if="currentRobotTask">{{ currentRobotTask.label }}</p>
          <progress :value="robotProgress" max="100" aria-label="当前路线完成进度" />
          <div class="robot-execution__state"><span>路线 {{ robotProgress }}%</span><span>{{ robotRemaining === null ? '等待任务反馈' : `预计 ${robotRemaining} 秒到达` }}</span></div>
          <p v-if="robot.state === 'arrived'">已到目标点。确认广播后才会产生广播完成证据。</p>
          <p v-else-if="robot.state === 'blocked'">先解除道路封锁，或重新规划路线。</p>
          <span>后续排队 {{ robot.task_queue?.filter(task => task.status === 'queued').length ?? 0 }} 项</span>
        </section>
        <dl v-if="selected.residentId && activeResident" class="resident-vitals"><div><dt>行为</dt><dd>{{ activeResident.behavior ?? '等待指令' }}</dd></div><div><dt>烟气暴露</dt><dd>{{ activeResident.smoke_exposure ?? 0 }}</dd></div><div><dt>拥堵指数</dt><dd>{{ activeResident.congestion ?? 0 }}</dd></div></dl>
        <button v-if="selected.vehicleId" type="button" @click="emit('dispatchVehicle', selected.vehicleId); selected = null">安排车辆 / 查看行程</button>
        <section v-if="assemblyCounts" class="assembly-attendance" aria-label="集合点到达与核验">
          <dl class="resident-vitals"><div><dt>真实到达</dt><dd>{{ assemblyCounts.arrived }} 人</dd></div><div><dt>已清点</dt><dd>{{ assemblyCounts.counted }} 人</dd></div><div><dt>分配此出口、尚未到达</dt><dd>{{ assemblyCounts.inbound }} 人</dd></div></dl>
          <p v-if="assemblyPending.length">待核验：{{ assemblyPending.map(person=>person.label).join('、') }}</p>
          <p v-else>{{ assemblyCounts.arrived ? '已到人员均已完成清点。' : '尚无居民到达，请先指挥居民疏散。' }}</p>
          <p>清点由参演端或训练教练提交，场景不会自动把“到达”改为“已清点”。</p>
        </section>
        <template v-if="selected.action === 'robot' && interactive">
          <button type="button" :disabled="robot?.state !== 'arrived' || operationBusy" @click="emit('robotCommand', 'broadcast')">{{ robot?.state === 'completed' ? '现场广播已完成' : robot?.state === 'arrived' ? '在此执行疏散广播' : '到达目标后可广播' }}</button>
          <button v-if="robot?.state === 'blocked'" type="button" :disabled="operationBusy" @click="emit('robotCommand', 'replan')">重新规划当前路线</button>
        </template>
        <button v-else-if="selected.action && interactive" type="button" @click="runSelectedAction">在此注入事件</button>
        <button v-if="selected.roadEdgeId && simulation?.road_network?.edges.find(e => e.id === selected?.roadEdgeId)?.status === 'blocked' && interactive" type="button" @click="emit('reopenRoad', selected.roadEdgeId)">解除此路段封锁</button>
        <button v-if="selected.residentId && interactive" type="button" @click="selectCurrentResident">指挥此居民</button>
        <button v-else-if="selected.action !== 'robot' && selected.x !== undefined && interactive" type="button" @click="pointRobotAtSelection">派机器人到此处</button>
        <button class="twin-inspector__assistant" type="button" @click="askAboutSelection"><AppIcon name="brain" :size="17" />问 AI 分析此对象</button>
        <p v-if="interactionNotice" role="status">{{ interactionNotice }}</p>
      </aside>

      <div v-if="isDraggingEvent" class="twin-drop-target">释放以注入演练事件</div>
      <div v-if="interactionNotice && !inspectorOpen" class="twin-interaction-notice" role="status">{{ interactionNotice }}</div>
      <div v-else-if="directorCue && !compact" class="director-cue" role="status"><span>自适应导演</span><strong>{{ directorCue }}</strong></div>
      <div v-if="renderError" class="twin-render-error" role="alert"><strong>{{ recoveringContext ? '正在恢复三维画面' : '三维画面暂不可用' }}</strong><p>{{ renderError }}</p></div>
    </div>
  </section>
</template>


<style scoped>
.spatial-marquee{position:absolute;z-index:15;pointer-events:none;border:1px solid #b5eede;background:#a2e9d329}.indoor-toggle{position:absolute;left:16px;bottom:155px;z-index:12;padding:10px 14px;border:1px solid #628a7d;border-radius:8px;background:#16392fee;color:#e9f2e9;font-size:13px;cursor:pointer;min-height:40px}.spatial-action-preview{position:absolute;z-index:16;right:4.75rem;bottom:4.7rem;width:min(25rem,calc(100% - 19rem));border:1px solid #5c8179;border-radius:.85rem;background:#edf1e9;color:#172c28;padding:1rem;box-shadow:0 22px 52px rgba(0,0,0,.34)}.spatial-action-preview header{display:flex;align-items:start;justify-content:space-between;gap:1rem;border-bottom:1px solid #c6d1cb;padding-bottom:.7rem}.spatial-action-preview header span,.spatial-action-preview header strong{display:block}.spatial-action-preview header span{color:#58716b;font-size:.65rem}.spatial-action-preview header strong{margin-top:.2rem;font-size:.9rem;overflow-wrap:anywhere}.spatial-action-preview header button{display:grid;place-items:center;flex:0 0 auto;width:2rem;height:2rem;border:0;border-radius:.4rem;background:transparent;color:#46605a}.spatial-action-loading{display:flex;align-items:center;gap:.65rem;padding:1.3rem 0;color:#58716b;font-size:.75rem}.spatial-action-loading i{width:1rem;height:1rem;border:2px solid #a8bbb5;border-top-color:#1b6a60;border-radius:50%;animation:spatial-spin .75s linear infinite}.spatial-action-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.4rem;margin-top:.75rem}.spatial-action-metrics>div{min-width:0;border:1px solid #d1d9d5;border-radius:.5rem;background:#f9faf6;padding:.55rem}.spatial-action-metrics span,.spatial-action-metrics strong{display:block}.spatial-action-metrics span{color:#71827e;font-size:.58rem}.spatial-action-metrics strong{margin-top:.18rem;font-size:.76rem;font-variant-numeric:tabular-nums}.spatial-action-metrics small{font-size:.58rem;font-weight:500}.spatial-impact{margin-top:.7rem;border-top:1px solid #c6d1cb;padding-top:.65rem}.spatial-impact>span{color:#9a4b36;font-size:.62rem;font-weight:700}.spatial-impact>div{display:grid;grid-template-columns:1fr 1fr;gap:.45rem;margin-top:.4rem}.spatial-impact p{display:flex;justify-content:space-between;gap:.4rem;margin:0;border-radius:.45rem;background:#e0e8e1;padding:.5rem;color:#58716b;font-size:.62rem}.spatial-impact p strong{color:#183b34;font-variant-numeric:tabular-nums}.spatial-action-note{margin:.7rem 0 0;color:#536b65;font-size:.67rem;line-height:1.55}.spatial-evidence{display:flex;align-items:center;gap:.4rem;margin:.55rem 0 0;color:#736025;font-size:.62rem}.spatial-action-buttons{display:grid;grid-template-columns:.7fr 1fr;gap:.5rem;margin-top:.8rem}.spatial-action-buttons button{display:flex;align-items:center;justify-content:center;gap:.35rem;min-height:2.5rem;border:1px solid #91a39e;border-radius:.55rem;background:transparent;color:#284b44;font-size:.7rem;font-weight:700}.spatial-action-buttons button:last-child{border-color:#1d685e;background:#1d685e;color:#fff}.spatial-action-buttons button:disabled{opacity:.45;cursor:not-allowed}@keyframes spatial-spin{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){.spatial-action-loading i{animation:none}}@media(max-width:900px){.spatial-action-preview{right:4rem;bottom:3.3rem;width:min(23rem,calc(100% - 15rem))}}@media(max-width:700px){.indoor-toggle{bottom:12px;left:12px}.spatial-action-preview{position:fixed;z-index:120;right:.55rem;bottom:4.4rem;left:.55rem;width:auto;max-height:calc(100dvh - 9rem);overflow:auto;padding:.85rem}.spatial-action-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}
.resident-pov-hud{position:absolute;z-index:11;right:1rem;bottom:1rem;width:min(27rem,calc(100% - 2rem));padding:.85rem 1rem;border:1px solid rgba(111,193,181,.42);border-radius:.7rem;background:rgba(5,25,23,.9);color:#edf8f4;box-shadow:0 18px 42px rgba(0,0,0,.32),inset 0 1px rgba(255,255,255,.06);backdrop-filter:blur(12px)}.resident-pov-hud header{display:flex;align-items:center;justify-content:space-between;gap:1rem}.resident-pov-hud header span,.resident-pov-hud header strong{display:block}.resident-pov-hud header span{color:#73cdbf;font-size:.6rem;letter-spacing:.1em}.resident-pov-hud header strong{margin-top:.18rem;font-size:.9rem}.resident-pov-hud>p{margin:.55rem 0 .7rem;color:#9eb6b0;font-size:.66rem}.resident-pov-switch{display:flex;gap:.25rem}.resident-pov-switch button{display:grid;place-items:center;width:2rem;height:2rem;border:1px solid #426c64;border-radius:.35rem;background:#103c36;color:#a8e2d7}.resident-pov-switch button:last-child svg{transform:rotate(180deg)}.resident-pov-grid{display:grid;grid-template-columns:1fr 1fr;gap:.4rem}.resident-pov-grid>span{min-width:0;padding:.46rem .55rem;border:1px solid rgba(112,153,144,.22);background:rgba(29,68,62,.45);color:#789a92;font-size:.57rem}.resident-pov-grid strong{display:block;margin-top:.18rem;overflow:hidden;color:#eaf4f0;font-size:.66rem;text-overflow:ellipsis;white-space:nowrap}.resident-pov-exposure{margin-top:.65rem}.resident-pov-exposure>span{display:flex;justify-content:space-between;color:#95aba6;font-size:.6rem}.resident-pov-exposure>span strong{color:#ff826b;font-variant-numeric:tabular-nums}.resident-pov-exposure>i{display:block;height:.28rem;margin-top:.3rem;overflow:hidden;border-radius:1rem;background:#263f3a}.resident-pov-exposure b{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,#58c9a4,#e8b64a 55%,#ff5640)}.risk-scale{display:grid!important;grid-template-columns:1fr auto;gap:.1rem .35rem!important;min-width:8.4rem}.risk-scale>i{grid-column:1/-1;width:100%;height:.28rem;border-radius:1rem;background:linear-gradient(90deg,#39c99b,#e2b03e 55%,#ff4935)}.risk-scale small{color:#a8bbb6;font-size:.55rem}.risk-scale small:last-child{text-align:right}.stair-density{padding:.18rem .35rem;border:1px solid rgba(255,180,61,.45);border-radius:.25rem;color:#ffd07a!important;background:rgba(118,68,15,.3)}
@media(max-width:700px){.resident-pov-hud{right:.55rem;bottom:9rem;width:calc(100% - 1.1rem);padding:.72rem}.resident-pov-grid{grid-template-columns:1fr 1fr}.resident-pov-hud>p{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.spatial-action-preview.spatial-action-preview--immersive{z-index:16;box-sizing:border-box;border:1px solid #4d7461;border-radius:7px;background:#08261e;color:#e5eee7;padding:20px;box-shadow:0 16px 38px #0005}
.spatial-action-preview--immersive header{border-color:#365948}.spatial-action-preview--immersive header strong{font-size:20px}.spatial-action-preview--immersive header span,.spatial-action-preview--immersive header button{color:#abc6b6}
.spatial-action-preview--immersive .spatial-action-metrics>div{background:#10392b;border-color:#39654e;border-radius:5px;padding:10px}.spatial-action-preview--immersive .spatial-action-metrics span{color:#b2cabc;font-size:11px}.spatial-action-preview--immersive .spatial-action-metrics strong{font-size:18px;color:#95eac0}.spatial-action-preview--immersive .spatial-action-metrics small{font-size:11px}
.spatial-action-preview--immersive .spatial-impact{border-color:#365948}.spatial-action-preview--immersive .spatial-impact>span{color:#eeb28a;font-size:12px}.spatial-action-preview--immersive .spatial-impact p{background:#163d2e;color:#b6cfbf;font-size:11px}.spatial-action-preview--immersive .spatial-impact p strong{color:#dceee2}
.spatial-score-impact{display:grid;grid-template-columns:1fr auto;gap:4px 12px;margin-top:12px;border-top:1px solid #c6d1cb;padding-top:12px}.spatial-score-impact>span{color:#58716b;font-size:13px}.spatial-score-impact>strong{font-size:16px;font-variant-numeric:tabular-nums}.spatial-score-impact>strong b{color:#9a4b36}.spatial-score-impact>small{grid-column:1/-1;color:#536b65;font-size:13px;line-height:1.55}.spatial-action-preview--immersive .spatial-action-note{color:#b8cfc0;font-size:14px;line-height:1.7}.spatial-action-preview--immersive .spatial-evidence{color:#d5c593;font-size:13px}.spatial-action-preview--immersive .spatial-action-buttons button{color:#deeee4;border-color:#5b866c;border-radius:5px;min-height:48px;font-size:14px}.spatial-action-preview--immersive .spatial-action-buttons button:last-child{background:#73dbab;color:#082a1b;border-color:#73dbab}.spatial-action-preview--immersive .spatial-score-impact{border-color:#365948}.spatial-action-preview--immersive .spatial-score-impact>span,.spatial-action-preview--immersive .spatial-score-impact>small{color:#b8cfc0}.spatial-action-preview--immersive .spatial-score-impact>strong{color:#e5eee7}.spatial-action-preview--immersive .spatial-score-impact>strong b{color:#f1c39f}
@media(max-width:760px){.spatial-action-preview.spatial-action-preview--immersive{padding:14px}}
</style>
