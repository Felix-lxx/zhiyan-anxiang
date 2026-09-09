<script setup lang="ts">
import type { MapObjectType, RoadEdgeStatus, MapObject, RoadNode, RoadEdge, ReachabilityResult } from '../domain/map'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import type { Community } from '../domain/models'
import AppIcon from './AppIcon.vue'
import UiConfirmDialog from './ui/UiConfirmDialog.vue'
import { createApiClient } from '../api/client'
import '../exercise.css'
import '../map-editor.css'



type CanvasTool = 'select' | 'place-object' | 'place-node' | 'connect'




interface CanvasPoint { x: number; y: number }
interface DragState { kind: 'object' | 'node'; id: string; origin: CanvasPoint; pointerId: number; moved: boolean }
interface PlanningIssue { id: string; tone: 'warning' | 'danger'; title: string; detail: string; layer: 'objects' | 'network'; targetId?: string; point?: CanvasPoint }

const props = defineProps<{ apiBaseUrl: string; accessToken: string; community: Community }>()
const emit = defineEmits<{ back: []; openScenes: [] }>()
const api = createApiClient(props.apiBaseUrl, () => props.accessToken)
const objectTypes: Array<{ value: MapObjectType; label: string }> = [
  { value: 'building', label: '楼栋' }, { value: 'road', label: '道路' }, { value: 'fire_lane', label: '消防通道' },
  { value: 'exit', label: '安全出口' }, { value: 'assembly_point', label: '集合点' }, { value: 'fire_hydrant', label: '消火栓' },
  { value: 'charging_shed', label: '充电棚' }, { value: 'micro_fire_station', label: '微型消防站' },
]

const objects = ref<MapObject[]>([])
const nodes = ref<RoadNode[]>([])
const edges = ref<RoadEdge[]>([])
const reachability = ref<ReachabilityResult | null>(null)
const selectedObjectId = ref<string | null>(null)
const selectedNodeId = ref<string | null>(null)
const selectedEdgeId = ref<string | null>(null)
const activeLayer = ref<'objects' | 'network'>('objects')
const networkPanel = ref<'nodes' | 'edges' | 'status'>('nodes')
const canvasTool = ref<CanvasTool>('select')
const placementType = ref<MapObjectType>('building')
const draftPoint = ref<CanvasPoint | null>(null)
const pointerPoint = ref<CanvasPoint>({ x: 50, y: 50 })
const connectionStartId = ref<string | null>(null)
const dragState = ref<DragState | null>(null)
const suppressedPointerClick = ref<string | null>(null)
const canvasRef = ref<HTMLElement | null>(null)
const objectNameInput = ref<HTMLInputElement | null>(null)
const nodeNameInput = ref<HTMLInputElement | null>(null)
const edgeNameInput = ref<HTMLInputElement | null>(null)
const diagnosticsOpen = ref(false)
const deleteConfirmationOpen = ref(false)
const isLoading = ref(true)
const isSaving = ref(false)
const isDeleting = ref(false)
const isNetworkLoading = ref(true)
const isNetworkSaving = ref(false)
const loadError = ref('')
const actionError = ref('')
const actionNotice = ref('')
const networkError = ref('')
const networkNotice = ref('')
const form = ref({ object_type: 'building' as MapObjectType, name: '', x: 50, y: 50, note: '' })
const nodeForm = ref({ name: '', x: 50, y: 50, is_exit: false })
const edgeForm = ref({ name: '', start_node_id: '', end_node_id: '', width_meters: 4, status: 'open' as RoadEdgeStatus })

const selectedObject = computed(() => objects.value.find((item) => item.id === selectedObjectId.value) ?? null)
const selectedNode = computed(() => nodes.value.find((item) => item.id === selectedNodeId.value) ?? null)
const connectionStart = computed(() => nodes.value.find((item) => item.id === connectionStartId.value) ?? null)
const currentVersion = computed(() => props.community.versions[props.community.versions.length - 1]?.name ?? '初始社区版本')
const gridStep = 2

const planningIssues = computed<PlanningIssue[]>(() => {
  const issues: PlanningIssue[] = []
  const degree = new Map(nodes.value.map((node) => [node.id, 0]))
  for (const edge of edges.value) {
    degree.set(edge.start_node_id, (degree.get(edge.start_node_id) ?? 0) + 1)
    degree.set(edge.end_node_id, (degree.get(edge.end_node_id) ?? 0) + 1)
    if (edge.width_meters < 3.5) {
      const start = nodeById(edge.start_node_id); const end = nodeById(edge.end_node_id)
      issues.push({ id: `narrow-${edge.id}`, tone: 'warning', title: `${edge.name}宽度不足`, detail: `${edge.width_meters} 米，消防车辆通行与人员对向疏散可能受限。`, layer: 'network', targetId: edge.id, point: start && end ? { x: (start.x + end.x) / 2, y: (start.y + end.y) / 2 } : undefined })
    }
  }
  for (const node of nodes.value) {
    if ((degree.get(node.id) ?? 0) === 0) issues.push({ id: `isolated-${node.id}`, tone: 'danger', title: `${node.name}未接入路网`, detail: '节点没有任何道路连接，无法参与疏散路径计算。', layer: 'network', targetId: node.id, point: { x: node.x, y: node.y } })
  }
  if (!nodes.value.some((node) => node.is_exit)) issues.push({ id: 'no-network-exit', tone: 'danger', title: '未设置疏散出口节点', detail: '至少需要一个出口节点才能检查完整撤离路径。', layer: 'network' })
  if (!objects.value.some((item) => item.object_type === 'fire_hydrant')) issues.push({ id: 'no-hydrant', tone: 'warning', title: '未登记消火栓', detail: '现场处置无法判断最近取水点。', layer: 'objects' })
  if (!objects.value.some((item) => item.object_type === 'assembly_point')) issues.push({ id: 'no-assembly', tone: 'warning', title: '未登记集合点', detail: '居民撤离后无法执行集合清点。', layer: 'objects' })
  for (const item of objects.value.filter((entry) => ['building', 'exit', 'fire_hydrant'].includes(entry.object_type))) {
    const nearest = nodes.value.length ? Math.min(...nodes.value.map((node) => Math.hypot(node.x - item.geometry.x, node.y - item.geometry.y))) : Infinity
    if (nearest > 25) issues.push({ id: `far-${item.id}`, tone: 'warning', title: `${item.name}远离道路节点`, detail: '与最近道路节点距离过大，正式演练可能出现路径跳跃。', layer: 'objects', targetId: item.id, point: item.geometry })
  }
  return issues
})

function mapUrl(objectId?: string): string { const base = `/communities/${props.community.id}/map-objects`; return objectId ? `${base}/${objectId}` : base }
function networkUrl(path = ''): string { return `/communities/${props.community.id}/road-network${path}` }
function typeLabel(type: MapObjectType): string { return objectTypes.find((item) => item.value === type)?.label ?? type }
function nodeById(nodeId: string): RoadNode | undefined { return nodes.value.find((node) => node.id === nodeId) }
function clamp(value: number): number { return Math.min(100, Math.max(0, value)) }
function snap(value: number): number { return clamp(Math.round(value / gridStep) * gridStep) }
function pointFromEvent(event: PointerEvent | MouseEvent): CanvasPoint {
  const rect = canvasRef.value?.getBoundingClientRect()
  if (!rect) return { x: 50, y: 50 }
  return { x: snap(((event.clientX - rect.left) / rect.width) * 100), y: snap(((event.clientY - rect.top) / rect.height) * 100) }
}
function clearMessages(): void { actionError.value = ''; actionNotice.value = ''; networkError.value = ''; networkNotice.value = '' }
function setLayer(layer: 'objects' | 'network'): void { activeLayer.value = layer; setTool('select'); draftPoint.value = null }
function setTool(tool: CanvasTool): void {
  canvasTool.value = tool; draftPoint.value = null; connectionStartId.value = null; clearMessages()
  if (tool === 'place-object') actionNotice.value = `在图上点击放置${typeLabel(placementType.value)}，坐标将自动吸附。`
  if (tool === 'place-node') networkNotice.value = '在图上点击确定道路节点位置。'
  if (tool === 'connect') networkNotice.value = '依次点击两个道路节点，预览连线后填写道路参数。'
}
function resetObjectForm(): void { form.value = { object_type: placementType.value, name: '', x: 50, y: 50, note: '' }; selectedObjectId.value = null; draftPoint.value = null; actionError.value = '' }
function resetNodeForm(): void { nodeForm.value = { name: '', x: 50, y: 50, is_exit: false }; selectedNodeId.value = null; draftPoint.value = null; networkError.value = '' }
function selectObject(mapObject: MapObject): void {
  selectedObjectId.value = mapObject.id; draftPoint.value = null
  form.value = { object_type: mapObject.object_type, name: mapObject.name, x: mapObject.geometry.x, y: mapObject.geometry.y, note: typeof mapObject.properties.note === 'string' ? mapObject.properties.note : '' }
  actionError.value = ''; actionNotice.value = ''
}
function selectNode(node: RoadNode): void {
  selectedNodeId.value = node.id; draftPoint.value = null
  nodeForm.value = { name: node.name, x: node.x, y: node.y, is_exit: node.is_exit }
  networkPanel.value = 'nodes'; networkError.value = ''; networkNotice.value = ''
}

async function loadObjects(): Promise<void> {
  isLoading.value = true; loadError.value = ''
  try {
    objects.value = await api.get<MapObject[]>(mapUrl())
  } catch (error) { loadError.value = error instanceof Error ? error.message : '无法读取社区地图，请稍后重试。' }
  finally { isLoading.value = false }
}
async function loadReachability(): Promise<void> {
  reachability.value = await api.get<ReachabilityResult>(networkUrl('/reachability'))
}
async function loadNetwork(): Promise<void> {
  isNetworkLoading.value = true; networkError.value = ''
  try {
    const payload = await api.get<{ nodes: RoadNode[]; edges: RoadEdge[] }>(networkUrl())
    nodes.value = payload.nodes; edges.value = payload.edges; await loadReachability()
    edgeForm.value.start_node_id ||= nodes.value[0]?.id ?? ''; edgeForm.value.end_node_id ||= nodes.value[1]?.id ?? ''
  } catch (error) { networkError.value = error instanceof Error ? error.message : '无法读取道路网络，请稍后重试。' }
  finally { isNetworkLoading.value = false }
}

function objectPayload(): Record<string, unknown> { return { object_type: form.value.object_type, name: form.value.name.trim(), geometry: { x: Number(form.value.x), y: Number(form.value.y) }, properties: form.value.note.trim() ? { note: form.value.note.trim() } : {} } }
async function saveObject(): Promise<void> {
  actionError.value = ''; actionNotice.value = ''; isSaving.value = true
  try {
    const editing = selectedObject.value
    const saved = editing ? await api.patch<MapObject>(mapUrl(editing.id), objectPayload()) : await api.post<MapObject>(mapUrl(), objectPayload())
    objects.value = editing ? objects.value.map((item) => item.id === saved.id ? saved : item) : [...objects.value, saved]
    selectObject(saved); canvasTool.value = 'select'; actionNotice.value = editing ? '对象属性与位置已保存。' : '对象已放置，可直接拖动调整。'
  } catch (error) { actionError.value = error instanceof Error ? error.message : '地图对象保存失败，请稍后重试。' }
  finally { isSaving.value = false }
}
async function saveNode(): Promise<void> {
  networkError.value = ''; networkNotice.value = ''; isNetworkSaving.value = true
  try {
    const editing = selectedNode.value; const body = { ...nodeForm.value, name: nodeForm.value.name.trim(), x: Number(nodeForm.value.x), y: Number(nodeForm.value.y) }
    const saved = editing ? await api.patch<RoadNode>(networkUrl(`/nodes/${editing.id}`), body) : await api.post<RoadNode>(networkUrl('/nodes'), body)
    nodes.value = editing ? nodes.value.map((item) => item.id === saved.id ? saved : item) : [...nodes.value, saved]
    selectNode(saved); canvasTool.value = 'select'; networkNotice.value = editing ? '节点信息与位置已保存。' : '道路节点已放置，可继续连接道路。'; await loadReachability()
  } catch (error) { networkError.value = error instanceof Error ? error.message : '道路节点保存失败，请稍后重试。' }
  finally { isNetworkSaving.value = false }
}
async function addEdge(): Promise<void> {
  networkError.value = ''; networkNotice.value = ''; isNetworkSaving.value = true
  try {
    const saved = await api.post<RoadEdge>(networkUrl('/edges'), { ...edgeForm.value, name: edgeForm.value.name.trim(), width_meters: Number(edgeForm.value.width_meters) })
    edgeForm.value.name = ''; connectionStartId.value = null; canvasTool.value = 'select'; selectedEdgeId.value = saved.id
    networkNotice.value = '道路已连接并写入当前版本。'; await loadNetwork(); networkPanel.value = 'status'
  } catch (error) { networkError.value = error instanceof Error ? error.message : '道路连接保存失败，请稍后重试。' }
  finally { isNetworkSaving.value = false }
}
async function changeEdgeStatus(edge: RoadEdge, status: RoadEdgeStatus): Promise<void> {
  const previous = edge.status; edge.status = status; networkError.value = ''; networkNotice.value = ''; isNetworkSaving.value = true
  try {
    await api.patch<RoadEdge>(networkUrl(`/edges/${edge.id}/status`), { status })
    networkNotice.value = '道路状态已更新，可达性已重算。'; await loadReachability()
  } catch (error) { edge.status = previous; networkError.value = `${error instanceof Error ? error.message : '道路状态更新失败。'} 已恢复原状态。` }
  finally { isNetworkSaving.value = false }
}

async function persistObjectPosition(id: string, origin: CanvasPoint): Promise<void> {
  const item = objects.value.find((entry) => entry.id === id); if (!item) return
  try {
    const saved = await api.patch<MapObject>(mapUrl(id), { geometry: item.geometry }); objects.value = objects.value.map((entry) => entry.id === id ? saved : entry); if (selectedObjectId.value === id) selectObject(saved)
    actionNotice.value = `${saved.name}已移动到 X ${saved.geometry.x}、Y ${saved.geometry.y}。`
  } catch (error) { item.geometry = origin; if (selectedObjectId.value === id) { form.value.x = origin.x; form.value.y = origin.y }; actionError.value = `${error instanceof Error ? error.message : '位置保存失败。'} 已恢复原位置。` }
}
async function persistNodePosition(id: string, origin: CanvasPoint): Promise<void> {
  const node = nodes.value.find((entry) => entry.id === id); if (!node) return
  try {
    const saved = await api.patch<RoadNode>(networkUrl(`/nodes/${id}`), { x: node.x, y: node.y }); nodes.value = nodes.value.map((entry) => entry.id === id ? saved : entry); if (selectedNodeId.value === id) selectNode(saved); await loadReachability()
    networkNotice.value = `${saved.name}的位置已保存，路网连线同步更新。`
  } catch (error) { node.x = origin.x; node.y = origin.y; if (selectedNodeId.value === id) { nodeForm.value.x = origin.x; nodeForm.value.y = origin.y }; networkError.value = `${error instanceof Error ? error.message : '节点位置保存失败。'} 已恢复原位置。` }
}
function startDrag(kind: 'object' | 'node', id: string, event: PointerEvent): void {
  if (canvasTool.value !== 'select' || event.button !== 0) return
  event.preventDefault(); event.stopPropagation()
  if (kind === 'object') { const item = objects.value.find((entry) => entry.id === id); if (!item) return; selectObject(item); dragState.value = { kind, id, origin: { ...item.geometry }, pointerId: event.pointerId, moved: false } }
  else { const node = nodes.value.find((entry) => entry.id === id); if (!node) return; selectNode(node); dragState.value = { kind, id, origin: { x: node.x, y: node.y }, pointerId: event.pointerId, moved: false } }
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
}
function handleCanvasPointerMove(event: PointerEvent): void {
  pointerPoint.value = pointFromEvent(event); const dragging = dragState.value; if (!dragging) return
  dragging.moved = dragging.moved || Math.hypot(pointerPoint.value.x - dragging.origin.x, pointerPoint.value.y - dragging.origin.y) >= gridStep
  if (dragging.kind === 'object') { const item = objects.value.find((entry) => entry.id === dragging.id); if (item) { item.geometry = { ...pointerPoint.value }; form.value.x = item.geometry.x; form.value.y = item.geometry.y } }
  else { const node = nodes.value.find((entry) => entry.id === dragging.id); if (node) { node.x = pointerPoint.value.x; node.y = pointerPoint.value.y; nodeForm.value.x = node.x; nodeForm.value.y = node.y } }
}
function finishDrag(event: PointerEvent): void {
  const dragging = dragState.value; if (!dragging || dragging.pointerId !== event.pointerId) return
  dragState.value = null; if (!dragging.moved) return
  suppressedPointerClick.value = `${dragging.kind}:${dragging.id}`
  if (dragging.kind === 'object') void persistObjectPosition(dragging.id, dragging.origin); else void persistNodePosition(dragging.id, dragging.origin)
}
function handleObjectClick(mapObject: MapObject): void {
  if (suppressedPointerClick.value === `object:${mapObject.id}`) { suppressedPointerClick.value = null; return }
  selectObject(mapObject)
}
async function nudge(kind: 'object' | 'node', id: string, event: KeyboardEvent): Promise<void> {
  const delta: Record<string, CanvasPoint> = { ArrowLeft: { x: -gridStep, y: 0 }, ArrowRight: { x: gridStep, y: 0 }, ArrowUp: { x: 0, y: -gridStep }, ArrowDown: { x: 0, y: gridStep } }
  if (!delta[event.key] || canvasTool.value !== 'select') return
  event.preventDefault(); const change = delta[event.key]
  if (kind === 'object') { const item = objects.value.find((entry) => entry.id === id); if (!item) return; const origin = { ...item.geometry }; item.geometry = { x: clamp(origin.x + change.x), y: clamp(origin.y + change.y) }; await persistObjectPosition(id, origin) }
  else { const node = nodes.value.find((entry) => entry.id === id); if (!node) return; const origin = { x: node.x, y: node.y }; node.x = clamp(origin.x + change.x); node.y = clamp(origin.y + change.y); await persistNodePosition(id, origin) }
}
function handleCanvasClick(event: MouseEvent): void {
  if ((event.target as HTMLElement).closest('.map-marker,.road-node,.network-hit-line,.map-diagnostic-pin')) return
  const point = pointFromEvent(event); draftPoint.value = point
  if (canvasTool.value === 'place-object' && activeLayer.value === 'objects') {
    selectedObjectId.value = null; form.value = { object_type: placementType.value, name: `${typeLabel(placementType.value)} ${objects.value.filter((item) => item.object_type === placementType.value).length + 1}`, x: point.x, y: point.y, note: '' }
    actionNotice.value = `已吸附到 X ${point.x}、Y ${point.y}，确认名称后保存。`; void nextTick(() => objectNameInput.value?.select())
  } else if (canvasTool.value === 'place-node' && activeLayer.value === 'network') {
    selectedNodeId.value = null; nodeForm.value = { name: `道路节点 ${nodes.value.length + 1}`, x: point.x, y: point.y, is_exit: false }; networkPanel.value = 'nodes'
    networkNotice.value = `节点位置为 X ${point.x}、Y ${point.y}，确认属性后保存。`; void nextTick(() => nodeNameInput.value?.select())
  }
}
function handleNodeClick(node: RoadNode): void {
  if (suppressedPointerClick.value === `node:${node.id}`) { suppressedPointerClick.value = null; return }
  if (canvasTool.value !== 'connect') { selectNode(node); return }
  if (!connectionStartId.value) { connectionStartId.value = node.id; networkNotice.value = `起点：${node.name}。现在点击另一个节点。`; return }
  if (connectionStartId.value === node.id) { connectionStartId.value = null; networkNotice.value = '已取消当前连线起点。'; return }
  const start = connectionStart.value; edgeForm.value.start_node_id = connectionStartId.value; edgeForm.value.end_node_id = node.id; edgeForm.value.name = `${start?.name ?? '起点'}—${node.name}通道`; connectionStartId.value = null; networkPanel.value = 'edges'; canvasTool.value = 'select'
  networkNotice.value = '连线路径已确定，请核对道路名称与宽度后保存。'; void nextTick(() => edgeNameInput.value?.select())
}
function selectEdge(edge: RoadEdge): void { selectedEdgeId.value = edge.id; networkPanel.value = 'status'; networkNotice.value = `已选择${edge.name}，可在右侧调整通行状态。` }
function focusIssue(issue: PlanningIssue): void {
  setLayer(issue.layer); diagnosticsOpen.value = true
  if (issue.layer === 'objects' && issue.targetId) { const item = objects.value.find((entry) => entry.id === issue.targetId); if (item) selectObject(item) }
  if (issue.layer === 'network' && issue.targetId) { const node = nodes.value.find((entry) => entry.id === issue.targetId); const edge = edges.value.find((entry) => entry.id === issue.targetId); if (node) selectNode(node); if (edge) selectEdge(edge) }
}
function requestDelete(): void { if (selectedObject.value) deleteConfirmationOpen.value = true }
async function deleteSelectedObject(): Promise<void> {
  const editing = selectedObject.value; if (!editing) return
  isDeleting.value = true; actionError.value = ''; actionNotice.value = ''
  try { await api.delete<unknown>(mapUrl(editing.id)); objects.value = objects.value.filter((item) => item.id !== editing.id); resetObjectForm(); actionNotice.value = '地图对象已删除。'; deleteConfirmationOpen.value = false }
  catch (error) { actionError.value = error instanceof Error ? error.message : '地图对象删除失败，请稍后重试。' }
  finally { isDeleting.value = false }
}

watch(placementType, (type) => { if (!selectedObject.value) form.value.object_type = type })
onMounted(() => { void loadObjects(); void loadNetwork() })
</script>

<template>
  <main id="main-content" class="workspace-shell map-editor">
    <header class="workspace-header">
      <button class="workspace-brand workspace-brand--button" type="button" @click="emit('back')"><AppIcon name="back" />智演安巷</button>
      <div class="workspace-header__tools"><button class="text-action" type="button" @click="emit('openScenes')"><AppIcon name="tasks" />场景草稿</button><button class="text-action" type="button" @click="emit('back')">返回项目登记</button></div>
    </header>

    <section class="workspace-content" aria-labelledby="map-title">
      <div class="map-heading">
        <div><h1 id="map-title">{{ community.name }} · 社区地图</h1><p>{{ community.address || '未登记地址' }} · {{ currentVersion }}</p></div>
        <p class="map-heading__note">直接在画布上布置对象、连接道路。所有位置变更实时保存到当前社区版本。</p>
      </div>

      <div class="map-workbench">
        <section class="map-stage" aria-label="社区地图编辑画布">
          <div class="map-stage__topline">
            <div class="map-layer-tabs" role="tablist" aria-label="地图图层"><button :aria-selected="activeLayer === 'objects'" role="tab" type="button" @click="setLayer('objects')">空间对象</button><button :aria-selected="activeLayer === 'network'" role="tab" type="button" @click="setLayer('network')">道路网络</button></div>
            <button class="map-check-button" type="button" :data-has-issues="planningIssues.length > 0" :aria-expanded="diagnosticsOpen" @click="diagnosticsOpen = !diagnosticsOpen"><AppIcon name="pulse" />规划检查 {{ planningIssues.length }}</button>
          </div>
          <div class="map-toolrail" role="toolbar" aria-label="地图编辑工具">
            <button type="button" :aria-pressed="canvasTool === 'select'" @click="setTool('select')"><AppIcon name="target" />选择与拖动</button>
            <template v-if="activeLayer === 'objects'"><select v-model="placementType" aria-label="待放置对象类型"><option v-for="type in objectTypes" :key="type.value" :value="type.value">{{ type.label }}</option></select><button type="button" :aria-pressed="canvasTool === 'place-object'" @click="setTool('place-object')"><AppIcon name="plus" />放置到图上</button></template>
            <template v-else><button type="button" :aria-pressed="canvasTool === 'place-node'" @click="setTool('place-node')"><AppIcon name="plus" />放置节点</button><button type="button" :disabled="nodes.length < 2" :aria-pressed="canvasTool === 'connect'" @click="setTool('connect')"><AppIcon name="route" />连接两点</button></template>
            <span class="map-coordinate-readout">X {{ pointerPoint.x }} · Y {{ pointerPoint.y }} · 吸附 {{ gridStep }}</span>
          </div>

          <div v-if="(activeLayer === 'objects' && isLoading) || (activeLayer === 'network' && isNetworkLoading)" class="map-canvas map-canvas--state">正在读取社区空间数据…</div>
          <div v-else-if="(activeLayer === 'objects' && loadError) || (activeLayer === 'network' && networkError && !nodes.length)" class="map-canvas map-canvas--state map-canvas--error" role="alert"><p>{{ activeLayer === 'objects' ? loadError : networkError }}</p><button class="secondary-button" type="button" @click="activeLayer === 'objects' ? loadObjects() : loadNetwork()">重新加载</button></div>
          <div v-else ref="canvasRef" class="map-canvas map-canvas--interactive" :data-tool="canvasTool" @click="handleCanvasClick" @pointermove="handleCanvasPointerMove" @pointerup="finishDrag" @pointercancel="finishDrag">
            <svg v-if="activeLayer === 'network'" class="network-lines" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
              <g v-for="edge in edges" :key="edge.id" @click.stop="selectEdge(edge)"><line class="network-hit-line" :x1="nodeById(edge.start_node_id)?.x" :y1="nodeById(edge.start_node_id)?.y" :x2="nodeById(edge.end_node_id)?.x" :y2="nodeById(edge.end_node_id)?.y" /><line :class="[`network-line--${edge.status}`, { 'network-line--selected': edge.id === selectedEdgeId }]" :x1="nodeById(edge.start_node_id)?.x" :y1="nodeById(edge.start_node_id)?.y" :x2="nodeById(edge.end_node_id)?.x" :y2="nodeById(edge.end_node_id)?.y" /></g>
              <line v-if="connectionStart" class="network-line--draft" :x1="connectionStart.x" :y1="connectionStart.y" :x2="pointerPoint.x" :y2="pointerPoint.y" />
            </svg>
            <p v-if="activeLayer === 'objects' && !objects.length && !draftPoint" class="map-empty-copy">选择上方对象类型，点击“放置到图上”，再在画布中确定位置。</p>
            <p v-if="activeLayer === 'network' && !nodes.length && !draftPoint" class="map-empty-copy">点击“放置节点”，先标出路口、楼门或疏散出口。</p>
            <button v-for="mapObject in activeLayer === 'objects' ? objects : []" :key="mapObject.id" class="map-marker" :class="`map-marker--${mapObject.object_type}`" :data-selected="mapObject.id === selectedObjectId" :data-dragging="dragState?.kind === 'object' && dragState.id === mapObject.id" :style="{ left: `${mapObject.geometry.x}%`, top: `${mapObject.geometry.y}%` }" type="button" :aria-label="`${mapObject.name}，拖动或使用方向键调整位置`" @pointerdown="startDrag('object', mapObject.id, $event)" @click.stop="handleObjectClick(mapObject)" @keydown="nudge('object', mapObject.id, $event)"><span>{{ typeLabel(mapObject.object_type) }}</span><strong>{{ mapObject.name }}</strong></button>
            <button v-for="node in activeLayer === 'network' ? nodes : []" :key="node.id" class="road-node" :class="{ 'road-node--exit': node.is_exit, 'road-node--isolated': reachability?.unreachable_node_ids.includes(node.id) }" :data-selected="node.id === selectedNodeId || node.id === connectionStartId" :data-dragging="dragState?.kind === 'node' && dragState.id === node.id" :style="{ left: `${node.x}%`, top: `${node.y}%` }" type="button" :aria-label="`${node.name}${node.is_exit ? '，疏散出口' : ''}`" @pointerdown="startDrag('node', node.id, $event)" @click.stop="handleNodeClick(node)" @keydown="nudge('node', node.id, $event)"><span>{{ node.is_exit ? '出口' : '节点' }}</span><strong>{{ node.name }}</strong></button>
            <div v-if="draftPoint" class="map-draft-marker" :style="{ left: `${draftPoint.x}%`, top: `${draftPoint.y}%` }"><span>待保存</span></div>
            <button v-for="issue in planningIssues.filter((item) => item.layer === activeLayer && item.point)" :key="issue.id" class="map-diagnostic-pin" :data-tone="issue.tone" :style="{ left: `${issue.point?.x}%`, top: `${issue.point?.y}%` }" type="button" :aria-label="issue.title" @click.stop="focusIssue(issue)">!</button>
            <aside v-if="diagnosticsOpen" class="map-diagnostics" aria-label="规划检查结果"><div><strong>规划检查</strong><button type="button" aria-label="关闭规划检查" @click="diagnosticsOpen = false"><AppIcon name="close" /></button></div><p v-if="!planningIssues.length">当前未发现基础空间配置问题。</p><button v-for="issue in planningIssues" v-else :key="issue.id" type="button" :data-tone="issue.tone" @click="focusIssue(issue)"><strong>{{ issue.title }}</strong><span>{{ issue.detail }}</span></button></aside>
          </div>
          <p class="map-stage__caption"><strong>{{ canvasTool === 'select' ? '操作：拖动对象调整位置；方向键可微调。' : canvasTool === 'connect' ? (connectionStart ? `已选择 ${connectionStart.name}，请点击终点。` : '依次点击两个节点创建道路。') : '点击画布确定位置，坐标自动吸附。' }}</strong><span>{{ activeLayer === 'objects' ? `${objects.length} 个对象` : `${nodes.length} 个节点 · ${edges.length} 条道路` }}</span></p>
        </section>

        <aside v-if="activeLayer === 'objects'" class="map-inspector" aria-labelledby="inspector-title">
          <div class="map-inspector__heading"><h2 id="inspector-title">{{ selectedObject ? '对象属性' : draftPoint ? '确认放置' : '空间对象' }}</h2><button v-if="selectedObject || draftPoint" class="text-action" type="button" :disabled="isSaving || isDeleting" @click="resetObjectForm">取消选择</button></div>
          <p>{{ selectedObject ? '属性修改与拖拽位置保存到同一社区版本。' : draftPoint ? '核对名称和位置后保存。' : '从画布上选择对象，或使用放置工具新增。' }}</p>
          <form class="map-object-form" @submit.prevent="saveObject">
            <label for="object-type">对象类型</label><select id="object-type" v-model="form.object_type"><option v-for="type in objectTypes" :key="type.value" :value="type.value">{{ type.label }}</option></select>
            <label for="object-name">对象名称</label><input id="object-name" ref="objectNameInput" v-model="form.name" required minlength="2" maxlength="120" placeholder="例如：1 号住宅楼" />
            <div class="coordinate-fields"><div><label for="object-x">横坐标 X</label><input id="object-x" v-model.number="form.x" type="number" required min="0" max="100" step="2" /></div><div><label for="object-y">纵坐标 Y</label><input id="object-y" v-model.number="form.y" type="number" required min="0" max="100" step="2" /></div></div>
            <p class="form-hint">坐标可精确输入，也可直接拖动图上对象。</p>
            <label for="object-note">现场备注 <span>可选</span></label><textarea id="object-note" v-model="form.note" rows="3" maxlength="500" placeholder="例如：六层住宅，东侧有疏散楼梯。"></textarea>
            <p v-if="actionError" class="message message--error" role="alert">{{ actionError }}</p><p v-if="actionNotice" class="message message--success" role="status">{{ actionNotice }}</p>
            <button class="primary-button" type="submit" :disabled="isSaving || isDeleting || (!selectedObject && !draftPoint)">{{ isSaving ? '正在保存…' : selectedObject ? '保存对象属性' : '确认放置对象' }}</button>
            <button v-if="selectedObject" class="danger-button" type="button" :disabled="isSaving || isDeleting" @click="requestDelete">删除此对象</button>
          </form>
        </aside>

        <aside v-else class="map-inspector network-inspector" aria-labelledby="network-title">
          <div class="map-inspector__heading"><h2 id="network-title">道路网络</h2><button class="text-action" type="button" :disabled="isNetworkLoading || isNetworkSaving" @click="loadNetwork">重新检查</button></div>
          <p>节点、道路宽度与通行状态共同决定疏散可达性。</p>
          <section v-if="reachability" class="reachability-result" :data-status="reachability.status" aria-live="polite"><strong>{{ reachability.summary }}</strong><p>出口 {{ reachability.exit_node_count }} 个 · 可达 {{ reachability.reachable_nodes }}/{{ reachability.total_nodes }} · 阻断 {{ reachability.blocked_edge_count }} 条</p></section>
          <nav class="network-editor-tabs" aria-label="道路网络编辑任务"><button type="button" :aria-pressed="networkPanel === 'nodes'" @click="networkPanel = 'nodes'"><AppIcon name="target" /><span>节点</span><b>{{ nodes.length }}</b></button><button type="button" :aria-pressed="networkPanel === 'edges'" @click="networkPanel = 'edges'"><AppIcon name="route" /><span>连线</span><b>{{ edges.length }}</b></button><button type="button" :aria-pressed="networkPanel === 'status'" @click="networkPanel = 'status'"><AppIcon name="pulse" /><span>状态</span><b>{{ edges.length }}</b></button></nav>
          <form v-if="networkPanel === 'nodes'" class="map-object-form network-form" @submit.prevent="saveNode">
            <div class="form-title-row"><h3>{{ selectedNode ? '编辑道路节点' : '确认节点位置' }}</h3><button v-if="selectedNode || draftPoint" class="text-action" type="button" @click="resetNodeForm">新增节点</button></div>
            <p class="form-hint">使用上方“放置节点”在画布确定位置，已保存节点可直接拖动。</p>
            <label for="node-name">节点名称</label><input id="node-name" ref="nodeNameInput" v-model="nodeForm.name" required minlength="2" maxlength="120" placeholder="例如：3 号楼路口" />
            <div class="coordinate-fields"><div><label for="node-x">横坐标 X</label><input id="node-x" v-model.number="nodeForm.x" type="number" required min="0" max="100" step="2" /></div><div><label for="node-y">纵坐标 Y</label><input id="node-y" v-model.number="nodeForm.y" type="number" required min="0" max="100" step="2" /></div></div>
            <label class="checkbox-field" for="node-exit"><input id="node-exit" v-model="nodeForm.is_exit" type="checkbox" />作为疏散出口节点</label>
            <button class="secondary-button" type="submit" :disabled="isNetworkSaving || (!selectedNode && !draftPoint)">{{ isNetworkSaving ? '正在保存…' : selectedNode ? '保存节点修改' : '确认放置节点' }}</button>
          </form>
          <form v-else-if="networkPanel === 'edges'" class="map-object-form network-form" @submit.prevent="addEdge">
            <h3>道路参数</h3><p class="form-hint">可用画布“连接两点”快速选择起终点，也可在此手动切换。</p>
            <p v-if="nodes.length < 2" class="network-inline-warning">至少需要两个道路节点。</p>
            <template v-else><label for="edge-name">道路名称</label><input id="edge-name" ref="edgeNameInput" v-model="edgeForm.name" required minlength="2" maxlength="120" placeholder="例如：北侧消防通道" /><div class="coordinate-fields"><div><label for="edge-start">起点</label><select id="edge-start" v-model="edgeForm.start_node_id"><option v-for="node in nodes" :key="node.id" :value="node.id">{{ node.name }}</option></select></div><div><label for="edge-end">终点</label><select id="edge-end" v-model="edgeForm.end_node_id"><option v-for="node in nodes" :key="node.id" :value="node.id">{{ node.name }}</option></select></div></div><label for="edge-width">有效宽度（米）</label><input id="edge-width" v-model.number="edgeForm.width_meters" type="number" required min="0.5" max="30" step="0.1" /><button class="secondary-button" type="submit" :disabled="isNetworkSaving || edgeForm.start_node_id === edgeForm.end_node_id">{{ isNetworkSaving ? '正在连接…' : '保存道路连接' }}</button></template>
          </form>
          <section v-else class="edge-register" aria-labelledby="edge-register-title"><h3 id="edge-register-title">道路通行状态</h3><div v-if="edges.length"><div v-for="edge in edges" :key="edge.id" class="edge-row" :data-selected="edge.id === selectedEdgeId" @click="selectedEdgeId = edge.id"><div><strong>{{ edge.name }}</strong><span>{{ nodeById(edge.start_node_id)?.name }} — {{ nodeById(edge.end_node_id)?.name }} · {{ edge.width_meters }} 米</span></div><select :value="edge.status" :disabled="isNetworkSaving" :aria-label="`${edge.name}通行状态`" @change="changeEdgeStatus(edge, ($event.target as HTMLSelectElement).value as RoadEdgeStatus)"><option value="open">畅通</option><option value="restricted">受限</option><option value="blocked">阻断</option></select></div></div><div v-else class="network-panel-empty"><AppIcon name="route" /><strong>尚无道路</strong><p>在画布上依次点击两个节点完成连线。</p><button class="secondary-button" type="button" @click="networkPanel = 'edges'; setTool('connect')">开始连接</button></div></section>
          <p v-if="networkError" class="message message--error" role="alert">{{ networkError }}</p><p v-if="networkNotice" class="message message--success" role="status">{{ networkNotice }}</p>
        </aside>
      </div>
    </section>
    <UiConfirmDialog :open="deleteConfirmationOpen" title="删除地图对象" :description="`确认删除“${selectedObject?.name ?? ''}”？当前编辑版本会立即更新，已冻结演练不受影响。`" confirm-label="删除对象" danger :busy="isDeleting" @cancel="deleteConfirmationOpen = false" @confirm="deleteSelectedObject" />
  </main>
</template>
