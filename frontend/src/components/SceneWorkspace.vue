<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ConfigurationIssue, ConfigurationValidation } from '../domain/validation'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import type { Community, MapObjectSummary, Scene, SceneTemplate } from '../domain/models'
import AppIcon from './AppIcon.vue'
import DecisionEditor from './DecisionEditor.vue'
import ScenePublishPanel from './ScenePublishPanel.vue'
import SceneLivePreview from './SceneLivePreview.vue'
import TrainingComparison from './TrainingComparison.vue'
import UiConfirmDialog from './ui/UiConfirmDialog.vue'
import ScenarioCasePicker from './ScenarioCasePicker.vue'
import '../scene-preview.css'
import '../atlas-scene.css'
import { createApiClient } from '../api/client'

interface Preview {
  fire_level: string; smoke_level: string; risk_level: string; affected_targets: string[]; route_advice: string; explanation: string
  simulation: Record<string, unknown> & { summary: { total: number; congested?: number; smoke_exposed?: number }; environment: { east_hydrant: string; south_lane: string; visibility?: number }; world: { parameters: Record<string, unknown>; spatial_network: { stair_width: number } } }
}
type WorkflowStep = 'parameters' | 'preview' | 'decisions' | 'publish'

const props = defineProps<{ apiBaseUrl: string; accessToken: string; community: Community }>()
const emit = defineEmits<{ back: []; openDrill: [sceneId: string, drillId: string] }>()
const api = createApiClient(props.apiBaseUrl, () => props.accessToken)
const route = useRoute(), router = useRouter()
const templates = ref<SceneTemplate[]>([])
const scenes = ref<Scene[]>([])
const chargingSheds = ref<MapObjectSummary[]>([])
const hasHousing = ref(false)
const sceneFireSources = ref<MapObjectSummary[]>([])
const loadingFireSources = ref(false)
const isLoading = ref(true)
const isSaving = ref(false)
const isPreviewing = ref(false)
const previewError = ref('')
const error = ref('')
const notice = ref('')
const selectedTemplateId = ref('')
const selectedSceneId = ref('')
const activeStep = ref<WorkflowStep>('parameters')
const name = ref('')
const parametersDirty = ref(false)
const parameterForm = ref({ fire_source_type: 'charging_shed', fire_source_object_id: '', fire_floor: 1, fire_room: 'east', room_door_state: 'open', start_time: '20:15', wind_direction: '微风', resident_count: 60, hydrant_status: 'faulty', south_lane_status: 'restricted', stair_width: 1.2 })
const parameterBaseline = ref({ ...parameterForm.value })
const previewMinute = ref(0)
const preparationStep = ref(1)
const validation = ref<ConfigurationValidation | null>(null)
const locationNotice = ref('')
const fieldSteps:Record<string,number>={'fire-source':2,'fire-floor':2,'fire-room':2,'room-door-state':2,'start-time':2,'wind-direction':2,'resident-count':1,'stair-width':1,'hydrant-status':1,'south-lane-status':1}
async function focusParameter(field:string){
  if(field==='scenario-tasks'){openPreparationStep(3);await nextTick();document.getElementById('scenario-tasks')?.focus();return}
  if(field==='scenario-template'){locationNotice.value=activeScene.value?.capabilities?.notice??'请检查案例支持情况。';preparationStep.value=4;return}
  if(!(field in fieldSteps))return
  preparationStep.value=fieldSteps[field];activeStep.value='parameters'
  await nextTick()
  const input=document.getElementById(field)
  input?.scrollIntoView({block:'center'});input?.focus({preventScroll:true})
  locationNotice.value='已定位待完善参数。修改后保存，再运行校验；不会改动已创建场次的冻结数据。'
}
function locateIssue(issue:ConfigurationIssue){guardUnsaved(()=>void focusParameter(issue.query.field))}
const validating = ref(false)
const preparationSteps = [
  ['社区底图', '楼栋、道路与基础设施'],
  ['人员与出口', '居民分布与疏散出口'],
  ['火源与烟气', '起火点与烟气扩散参数'],
  ['机器人', '任务策略与处置分支'],
  ['校验', '完整性与风险检查'],
]
async function validateCurrent() {
  if (!activeScene.value) return
  validating.value = true; error.value = ''
  try { validation.value = await api.post('/scenes/' + activeScene.value.id + '/validate') }
  catch(cause) { error.value = cause instanceof Error ? cause.message : '校验失败，请重试。' }
  finally { validating.value = false }
}
function openPreparationStep(index: number) {
  const change = () => { preparationStep.value = index; activeStep.value = index === 4 ? 'publish' : index === 3 ? 'decisions' : 'parameters'; if(index === 4) void validateCurrent() }
  if(index >= 3) guardUnsaved(change); else change()
}
function openMapEditor() { guardUnsaved(() => { void router.push({name:'map', params:{communityId: props.community.id}}) }) }
const preview = ref<Preview | null>(null)
const discardConfirmationOpen = ref(false)
const comparisonSceneId = ref('')
let previewRequest = 0
let previewTimer: number | null = null
let previewController: AbortController | null = null
let pendingDiscardAction: (() => void) | null = null
let resolveLeave: ((value: boolean) => void) | null = null

const activeScene = computed(() => scenes.value.find((scene) => scene.id === selectedSceneId.value) ?? null)
const activeCanRun = computed(() => Boolean(activeScene.value?.capabilities?.can_run))
const isKitchen = computed(() => activeScene.value?.capabilities?.code === 'kitchen_fire')
const sourceFloors = computed(() => sceneFireSources.value.find(source=>source.id===parameterForm.value.fire_source_object_id)?.floors ?? 1)
const selectedTemplate = computed(() => templates.value.find(template=>template.id===selectedTemplateId.value))
const canCreateOnMap = computed(() => selectedTemplate.value?.code === 'kitchen_fire' ? hasHousing.value : chargingSheds.value.length > 0)
const activeVersion = computed(() => activeScene.value ? latestVersion(activeScene.value) : null)
const selectedSourceName = computed(() => sceneFireSources.value.find(source => source.id === parameterForm.value.fire_source_object_id)?.name ?? '尚未选择合法火点')
const fireSourceSelection = computed(() => preparationStep.value !== 2 || !activeCanRun.value || isKitchen.value ? undefined : ({ enabled: !isSaving.value && !loadingFireSources.value,
  selectedId: parameterForm.value.fire_source_object_id, eligibleIds: sceneFireSources.value.map(source => source.id) }))
const comparisonScene = computed(() => scenes.value.find(scene => scene.id === comparisonSceneId.value) ?? null)
const previewIsDraft = computed(() => parametersDirty.value || !activeVersion.value?.parameters.fire_source_object_id)
const workflowSteps: Array<{ id: WorkflowStep; label: string; helper: string; icon: string }> = [
  { id: 'parameters', label: '基本参数', helper: '定义火情与资源', icon: 'fire' },
  { id: 'preview', label: '空间预览', helper: '验证风险变化', icon: 'eye' },
  { id: 'decisions', label: '决策任务', helper: '编排处置分支', icon: 'split' },
  { id: 'publish', label: '校验发布', helper: '冻结可运行版本', icon: 'check' },
]

function latestVersion(scene: Scene) { return scene.versions[scene.versions.length - 1] ?? null }
function startNewScene(){guardUnsaved(()=>{if(previewTimer)window.clearTimeout(previewTimer);previewTimer=null;selectedSceneId.value='';preview.value=null;previewRequest++;previewController?.abort();validation.value=null;error.value='';notice.value='';previewError.value='';isPreviewing.value=false;void nextTick(()=>document.querySelector<HTMLInputElement>('#scenario-name')?.focus())})}
function guardUnsaved(action: () => void) {
  if (isSaving.value) { notice.value = '正在保存当前版本，请稍候再切换。'; return }
  if (!parametersDirty.value) { action(); return }
  pendingDiscardAction = action
  discardConfirmationOpen.value = true
}
function confirmDiscard() {
  const originalId = selectedSceneId.value
  if (activeScene.value) hydrateParameters(activeScene.value)
  parametersDirty.value = false
  discardConfirmationOpen.value = false
  const action = pendingDiscardAction
  pendingDiscardAction = null
  action?.()
  if (activeScene.value && selectedSceneId.value === originalId) void loadPreview(activeScene.value.id, previewIsDraft.value)
  resolveLeave?.(true); resolveLeave = null
}
function cancelDiscard() { discardConfirmationOpen.value = false; pendingDiscardAction = null; resolveLeave?.(false); resolveLeave = null }
onBeforeRouteLeave(() => {
  if (isSaving.value) return false
  if (!parametersDirty.value) return true
  discardConfirmationOpen.value = true
  return new Promise<boolean>(resolve => { resolveLeave = resolve })
})
function hydrateParameters(scene: Scene) {
  const p = latestVersion(scene)?.parameters ?? {}
  parameterForm.value = {
    fire_source_type: isKitchen.value ? 'kitchen' : 'charging_shed', fire_floor: Number(p.fire_floor ?? 1), fire_room: String(p.fire_room ?? 'east'), room_door_state: String(p.room_door_state ?? 'open'),
    fire_source_object_id: String(p.fire_source_object_id ?? ''), start_time: String(p.start_time ?? '20:15'), wind_direction: String(p.wind_direction ?? '微风'), resident_count: Number(p.resident_count ?? (isKitchen.value?24:60)), hydrant_status: String(p.hydrant_status ?? 'faulty'), south_lane_status: String(p.south_lane_status ?? 'restricted'), stair_width: Number(p.stair_width ?? 1.2),
  }
  parameterBaseline.value = { ...parameterForm.value }
  parametersDirty.value = false
}
function selectScene(scene: Scene, step: WorkflowStep = 'parameters') {
  guardUnsaved(() => {
    if (previewTimer) window.clearTimeout(previewTimer)
    previewController?.abort()
    preview.value = null; previewRequest += 1
    selectedSceneId.value = scene.id
    activeStep.value = step
    preparationStep.value = step === 'publish' ? 4 : step === 'decisions' ? 3 : 1
    validation.value = null
    error.value = ''; notice.value = ''; previewError.value = ''
    hydrateParameters(scene)
    void loadFireSources(scene.id)
  })
}
let fireSourcesRequest = 0
async function loadFireSources(sceneId: string) {
  const request = ++fireSourcesRequest
  loadingFireSources.value = true; sceneFireSources.value = []; previewError.value = ''
  try {
    const sources = await api.get<MapObjectSummary[]>(`/scenes/${sceneId}/fire-sources`)
    if (request !== fireSourcesRequest || selectedSceneId.value !== sceneId) return
    sceneFireSources.value = sources
    if (!parameterForm.value.fire_source_object_id && sources[0]) {
      parameterForm.value.fire_source_object_id = sources[0].id
      parameterBaseline.value.fire_source_object_id = sources[0].id
    }
    await loadPreview(sceneId, previewIsDraft.value)
  } catch (cause) {
    if (request === fireSourcesRequest && selectedSceneId.value === sceneId) previewError.value = cause instanceof Error ? cause.message : '火点列表读取失败，请重新选择场景。'
  } finally { if (request === fireSourcesRequest) loadingFireSources.value = false }
}
function selectFireSource(id: string) {
  if (!fireSourceSelection.value?.enabled || !sceneFireSources.value.some(source => source.id === id)) return
  if (id === parameterForm.value.fire_source_object_id) return
  parameterForm.value.fire_source_object_id = id
  handleParameterChange()
  notice.value = `已选择${selectedSourceName.value}，正在试算；保存后才会应用于新场次。`
}
function undoFireSource() {
  parameterForm.value.fire_source_object_id = parameterBaseline.value.fire_source_object_id
  parameterForm.value.fire_floor = parameterBaseline.value.fire_floor
  parameterForm.value.fire_room = parameterBaseline.value.fire_room
  parameterForm.value.room_door_state = parameterBaseline.value.room_door_state
  handleParameterChange()
  notice.value = '已撤销火点选择，其他参数保持不变。'
}
function toggleComparison(scene: Scene) {
  comparisonSceneId.value = comparisonSceneId.value === scene.id ? '' : scene.id
}

async function load() {
  isLoading.value = true; error.value = ''
  try {
    const [ta, sb, objects] = await Promise.all([
      api.get<SceneTemplate[]>('/scene-templates'), api.get<Scene[]>(`/communities/${props.community.id}/scenes`), api.get<MapObjectSummary[]>(`/communities/${props.community.id}/map-objects`),
    ])
    templates.value = ta; scenes.value = sb; chargingSheds.value = objects.filter((item) => item.object_type === 'charging_shed'); hasHousing.value=objects.some(item=>item.object_type==='building')
    const requestedTemplate=templates.value.find(t=>t.code===route.query.case&&t.capabilities.can_create)
    if(requestedTemplate){selectedTemplateId.value=requestedTemplate.id;selectedSceneId.value='';name.value=requestedTemplate.name;return}
    if (!templates.value.some(t=>t.id===selectedTemplateId.value&&t.capabilities.can_create)) selectedTemplateId.value = templates.value.find(t=>t.capabilities.can_create)?.id??''
    if (!parameterForm.value.fire_source_object_id && chargingSheds.value[0]) parameterForm.value.fire_source_object_id = chargingSheds.value[0].id
    const saved = scenes.value.find(scene => scene.id === route.query.scene) ?? scenes.value[0]
    if (saved) { selectScene(saved, workflowSteps.some(step => step.id === route.query.step) ? route.query.step as WorkflowStep : 'parameters'); const tab=Number(route.query.preparation); if(route.query.preparation!==undefined&&Number.isInteger(tab)&&tab>=0&&tab<=4)preparationStep.value=tab }
  } catch (caught) { error.value = caught instanceof Error ? caught.message : '场景工作台加载失败。' } finally { isLoading.value = false }
  if(activeScene.value && typeof route.query.field==='string')await focusParameter(route.query.field)
}
async function createScene() {
  if(!selectedTemplate.value?.capabilities.can_create)return
  error.value = ''; notice.value = ''; isSaving.value = true
  try {
    const scene = await api.post<Scene>(`/communities/${props.community.id}/scenes`, { template_id: selectedTemplateId.value, name: name.value.trim() })
    scenes.value = [scene, ...scenes.value]; name.value = ''; isSaving.value = false; selectScene(scene); notice.value = '场景草稿已创建，请核对并保存基本参数。'
    await router.replace({query:{scene:scene.id}})
  } catch (caught) { error.value = caught instanceof Error ? caught.message : '场景草稿创建失败。' } finally { isSaving.value = false }
}
async function saveParameters() {
  if (!activeScene.value || !activeCanRun.value) return
  const previousVersion = activeVersion.value?.version_number ?? 0
  const sceneId = activeScene.value.id
  const savedForm = { ...parameterForm.value }
  error.value = ''; notice.value = ''; isSaving.value = true
  try {
    const updated = await api.patch<Scene>(`/scenes/${sceneId}/parameters`, savedForm)
    scenes.value = scenes.value.map((scene) => scene.id === updated.id ? updated : scene)
    const createdDraft = (latestVersion(updated)?.version_number ?? 0) > previousVersion
    if (selectedSceneId.value !== sceneId) return
    parameterBaseline.value = savedForm
    parametersDirty.value = JSON.stringify(parameterForm.value) !== JSON.stringify(savedForm)
    notice.value = parametersDirty.value ? '该版本已保存；保存期间的新修改仍未保存。' : createdDraft ? '已派生新草稿，旧场次与回放保持原火点。' : '参数已保存，新场次将冻结此火点。'
    activeStep.value = 'preview'
    await loadPreview(updated.id, previewIsDraft.value)
  } catch (caught) { error.value = caught instanceof Error ? caught.message : '参数保存失败。' } finally { isSaving.value = false }
}
function validPreviewParameters(): boolean {
  const value = parameterForm.value
  return Boolean(activeCanRun.value && !loadingFireSources.value && sceneFireSources.value.some(source => source.id === value.fire_source_object_id) && /^([01]\d|2[0-3]):[0-5]\d$/.test(value.start_time) && value.resident_count >= 1 && value.resident_count <= (isKitchen.value?sourceFloors.value*8:1000) && value.stair_width >= .6 && value.stair_width <= 3)
}
function schedulePreview() {
  if (previewTimer) window.clearTimeout(previewTimer)
  previewRequest++; previewController?.abort()
  if (!activeScene.value || !validPreviewParameters()) {
    previewRequest++; previewController?.abort(); isPreviewing.value = false
    previewError.value = activeScene.value ? isKitchen.value?`请检查房间、时间、楼梯宽度及人口；当前示例住宅上限 ${sourceFloors.value*8} 人。`:'请检查起火点、时间、人数和楼梯宽度。' : ''
    return
  }
  isPreviewing.value=true
  previewTimer = window.setTimeout(() => void loadPreview(activeScene.value!.id, true), 360)
}
function handleParameterChange() { if(isKitchen.value)parameterForm.value.fire_floor=Math.max(1,Math.min(sourceFloors.value,parameterForm.value.fire_floor)); parametersDirty.value = JSON.stringify(parameterForm.value) !== JSON.stringify(parameterBaseline.value); validation.value = null; schedulePreview() }
function selectFireRoom(value:{floor:number;room:string}) { if(isSaving.value || !isKitchen.value)return;parameterForm.value.fire_floor=value.floor;parameterForm.value.fire_room=value.room;handleParameterChange() }
function handlePreviewMinuteChange() {
  if (!activeScene.value) return
  if (previewTimer) window.clearTimeout(previewTimer)
  previewTimer = window.setTimeout(() => void loadPreview(activeScene.value!.id, previewIsDraft.value), 180)
}
async function loadPreview(sceneId: string, draft = previewIsDraft.value) {
  const scene=scenes.value.find(item=>item.id===sceneId)
  if(!scene?.capabilities?.can_preview){previewRequest++;previewController?.abort();preview.value=null;isPreviewing.value=false;previewError.value=scene?.capabilities?.notice??'暂时无法读取案例能力，请重新打开场景。';return}
  const request = ++previewRequest
  previewController?.abort()
  previewController = new AbortController()
  previewError.value = ''; isPreviewing.value = true
  try {
    const path = `/scenes/${sceneId}/preview?minute=${previewMinute.value}`
    const payload = draft
      ? await api.post<Preview>(path, parameterForm.value, { signal: previewController.signal })
      : await api.get<Preview>(path, { signal: previewController.signal })
    if (request === previewRequest) preview.value = payload
  } catch (caught) { if (request === previewRequest && !(caught instanceof DOMException && caught.name === 'AbortError')) previewError.value = caught instanceof Error ? caught.message : '预览生成失败。' } finally { if (request === previewRequest) isPreviewing.value = false }
}
function handlePublished() {
  if (!activeScene.value) return
  const id = activeScene.value.id
  scenes.value = scenes.value.map((scene) => scene.id === id ? { ...scene, status: 'published' } : scene)
}
async function repairTasks() {
  if(!activeScene.value || isSaving.value)return
  const sceneId=activeScene.value.id
  isSaving.value=true;error.value=''
  try {
    const value=await api.post<Scene>(`/scenes/${sceneId}/repair-tasks`)
    scenes.value=scenes.value.map(s=>s.id===value.id?value:s)
    notice.value='标准处置任务已补齐。已发布场景会生成新草稿，原演练不变；请重新校验发布。'
    await validateCurrent()
  }catch(cause){error.value=cause instanceof Error?cause.message:'补齐任务失败，请重试。'}finally{isSaving.value=false}
}
function handleBeforeUnload(event: BeforeUnloadEvent) { if (parametersDirty.value) event.preventDefault() }
watch([selectedSceneId, activeStep, preparationStep], () => {
  if (isLoading.value || route.name !== 'scenes') return
  void router.replace({ query: { ...route.query, scene: selectedSceneId.value || undefined, step: selectedSceneId.value ? activeStep.value : undefined, preparation: selectedSceneId.value ? String(preparationStep.value) : undefined } })
})
onMounted(() => { window.addEventListener('beforeunload', handleBeforeUnload); void load() })
onBeforeUnmount(() => { fireSourcesRequest++; previewRequest++; window.removeEventListener('beforeunload', handleBeforeUnload); if (previewTimer) window.clearTimeout(previewTimer); previewController?.abort() })
</script>

<template>
  <main id="main-content" class="atlas-preparation">
    <header class="atlas-preparation__bar"><button title="智演安巷——面向老旧小区消防治理的数字孪生与智能决策平台" @click="router.push('/projects')"><AppIcon name="building" :size="28"/><strong>智演安巷</strong><span>消防治理智能决策平台</span></button><nav><button aria-current="page">场景准备</button><button :disabled="!activeCanRun || activeScene?.status !== 'published'" @click="router.push({name:'operations',params:{communityId:community.id},query:{scene:activeScene?.id,autostart:'1'}})">演练推演</button><button @click="router.push({name:'projects',query:{section:'history'}})">过程复盘</button><button @click="openMapEditor">资源管理</button></nav><span>{{community.name.split(' · ')[0]}}</span></header>
    <header class="atlas-preparation__heading"><h1>场景准备</h1><span class="atlas-preparation__breadcrumb">{{community.name}} / {{activeScene?.name || '创建场景'}}</span><span v-if="activeScene" class="status-badge" :data-status="activeScene.status">{{parametersDirty ? '未保存' : activeScene.status==='published'?'已发布':'草稿'}}</span><div v-if="activeScene"><button class="secondary-button" :disabled="isSaving || !validPreviewParameters()" @click="saveParameters"><AppIcon name="check" :size="17"/>{{isSaving?'保存中…':'保存草稿'}}</button><button class="primary-button" @click="openPreparationStep(4)"><AppIcon name="lock" :size="17"/>冻结场景</button></div></header>
    <p v-if="error" class="message message--error" role="alert">{{error}}</p><p v-if="notice" class="atlas-preparation__notice" role="status">{{notice}}</p>
    <section v-if="!activeScene" class="atlas-scene-empty"><h2>{{isLoading?'正在读取场景…':'创建演练场景'}}</h2><form v-if="!isLoading" @submit.prevent="createScene"><ScenarioCasePicker v-model="selectedTemplateId" :templates="templates"/><label for="scenario-name">场景名称<input id="scenario-name" v-model="name" required minlength="2" maxlength="120" placeholder="例如：安巷社区消防演练"/></label><button class="primary-button" :disabled="isSaving || !selectedTemplate?.capabilities.can_create || !canCreateOnMap">{{isSaving?'正在创建…':'创建场景草稿'}}</button><button type="button" class="secondary-button" @click="openMapEditor">编辑社区底图</button><button v-if="scenes.length" type="button" class="secondary-button" @click="selectScene(scenes[0]!)">返回已有场景</button><p v-if="!canCreateOnMap">请先在社区底图添加{{selectedTemplate?.code==='kitchen_fire'?'住宅楼':'充电棚'}}。</p></form></section>
    <section v-else class="atlas-preparation__workspace">
      <nav class="atlas-preparation__steps" aria-label="场景配置步骤"><button v-for="(step,i) in preparationSteps" :key="step[0]" :aria-current="preparationStep===i?'step':undefined" @click="openPreparationStep(i)"><b>{{i+1}}</b><span><strong>{{step[0]}}</strong><small>{{step[1]}}</small></span></button><label>当前场景<select :value="selectedSceneId" @change="selectScene(scenes.find(s=>s.id===($event.target as HTMLSelectElement).value)!)"><option v-for="s in scenes" :key="s.id" :value="s.id">{{s.name}}</option></select></label><button type="button" class="atlas-preparation__new-scene" @click="startNewScene"><AppIcon name="plus" :size="18"/>新建场景</button></nav>
      <div class="atlas-preparation__canvas">
        <SceneLivePreview :simulation="preview?.simulation ?? null" :loading="isPreviewing || loadingFireSources" :error="previewError" :minute="previewMinute" :draft="previewIsDraft" :fire-level="preview?.fire_level" :smoke-level="preview?.smoke_level" :risk-level="preview?.risk_level" :fire-source-selection="fireSourceSelection" :selected-source-name="selectedSourceName" :room-selection="isKitchen && preparationStep===2 && !isSaving" @fire-source-pick="selectFireSource" @fire-room-pick="selectFireRoom"/>
        <div class="atlas-preparation__preview-time"><AppIcon name="clock" :size="17"/><label for="preview-minute">推演时刻 {{previewMinute}} 分钟</label><input id="preview-minute" v-model.number="previewMinute" type="range" min="0" max="10" @input="handlePreviewMinuteChange"/><button :disabled="isPreviewing" aria-label="重新计算预览" @click="loadPreview(activeScene.id)"><AppIcon name="refresh" :size="17"/></button></div>
      </div>
      <aside class="atlas-preparation__inspector">
       <p v-if="locationNotice" class="configuration-location" role="status">{{locationNotice}}</p>
       <section v-if="!activeCanRun" class="scenario-unavailable" aria-label="案例支持情况"><h2>{{activeScene.capabilities?.title??'案例能力待确认'}}</h2><p>{{activeScene.capabilities?.notice??'未能读取案例运行能力，请重新进入场景准备。'}}</p><button type="button" class="primary-button" @click="startNewScene">选择可演练案例</button><button type="button" class="secondary-button" @click="router.push({name:'projects',query:{section:'history'}})">查看历史演练</button></section>
       <template v-else-if="preparationStep===0"><h2>社区底图</h2><p>楼栋、道路、消防设施与集合点</p><div class="atlas-property-group"><h3>当前社区</h3><strong>{{community.name}}</strong><p>{{community.address || '尚未填写地址'}}</p><button class="primary-button" @click="openMapEditor">打开地图编辑器</button></div><div class="atlas-property-group"><h3>场景关联</h3><p>保存后的社区坐标和路网进入当前三维预览；发布时冻结为运行版本。</p><button class="secondary-button" @click="toggleComparison(activeScene)">方案对比</button><TrainingComparison v-if="comparisonScene" :key="comparisonScene.id" :api-base-url="apiBaseUrl" :access-token="accessToken" :scene-id="comparisonScene.id" :scene-name="comparisonScene.name" @close="comparisonSceneId=''" @open-drill="id=>emit('openDrill',activeScene!.id,id)"/></div></template>
       <form v-else-if="preparationStep===1 || preparationStep===2" class="atlas-properties" @submit.prevent="saveParameters" @input="handleParameterChange" @change="handleParameterChange"><h2>{{preparationStep===1?'人员与南侧通道':'火源与烟气'}}</h2><p>{{preparationStep===1?'配置居民规模、楼梯容量与疏散条件':'配置起火点、时刻和环境条件'}}</p>
        <p v-if="isKitchen && preparationStep===1">厨房案例使用一栋住宅的示例户型，每层最多 8 人；当前容量 {{sourceFloors*8}} 人。</p>
        <div v-if="preparationStep===1" class="atlas-property-group"><h3>基本信息</h3><label for="resident-count">参演居民数 <span>人</span></label><input id="resident-count" v-model.number="parameterForm.resident_count" type="number" min="1" max="1000" required/><label for="stair-width">楼梯净宽 <span>米</span></label><input id="stair-width" v-model.number="parameterForm.stair_width" type="number" min=".6" max="3" step=".1" required/><label for="south-lane-status">当前通道状态</label><select id="south-lane-status" v-model="parameterForm.south_lane_status"><option value="open">畅通</option><option value="restricted">受限</option><option value="blocked">阻断</option></select><label for="hydrant-status">东侧消火栓</label><select id="hydrant-status" v-model="parameterForm.hydrant_status"><option value="available">可用</option><option value="faulty">故障待替代</option></select></div>
        <div v-else class="atlas-property-group">
          <h3>起火位置</h3>
          <label for="fire-source">{{isKitchen?'起火住宅楼':'充电棚对象'}}</label>
          <select id="fire-source" v-model="parameterForm.fire_source_object_id" :disabled="isSaving || loadingFireSources" aria-describedby="fire-source-help" required>
            <option v-if="!sceneFireSources.some(source=>source.id===parameterForm.fire_source_object_id)" :value="parameterForm.fire_source_object_id" disabled>{{loadingFireSources?'正在读取火点…':'请选择合法火点'}}</option>
            <option v-for="shed in sceneFireSources" :key="shed.id" :value="shed.id">{{shed.name}}</option>
          </select>
          <p id="fire-source-help">{{isKitchen?'选择楼栋、楼层与厨房，三维自动进入对应楼内剖面。':'可直接点选三维中的高亮充电棚，也可使用此列表选择。'}}预览只试算，已有演练不受影响。</p>
          <template v-if="isKitchen">
            <label for="fire-floor">起火楼层</label><select id="fire-floor" v-model.number="parameterForm.fire_floor"><option v-for="floor in sourceFloors" :key="floor" :value="floor">{{floor}} 层</option></select>
            <label for="fire-room">起火厨房</label><select id="fire-room" v-model="parameterForm.fire_room"><option value="east">东侧厨房</option><option value="west">西侧厨房</option></select>
            <label for="room-door-state">起火房门初始状态</label><select id="room-door-state" v-model="parameterForm.room_door_state"><option value="open">打开 · 人员可通行、烟气交换较快</option><option value="closed">关闭 · 阻断通行、减少烟气交换</option></select>
            <p>关闭房门会影响房内人员撤离，演练中可在「楼内烟气与门控」查看本层人员并调整房门。</p>
          </template>
          <button type="button" class="secondary-button fire-source-undo" :disabled="isSaving || (parameterForm.fire_source_object_id===parameterBaseline.fire_source_object_id && parameterForm.fire_floor===parameterBaseline.fire_floor && parameterForm.fire_room===parameterBaseline.fire_room && parameterForm.room_door_state===parameterBaseline.room_door_state)" @click="undoFireSource"><AppIcon name="refresh" :size="17"/>撤销火点选择</button>
          <div v-if="!loadingFireSources && !sceneFireSources.length"><p role="alert">没有读取到合法{{isKitchen?'住宅楼':'充电棚'}}。可重新读取；若底图缺项，请在地图编辑器补齐。</p><button type="button" class="secondary-button fire-source-undo" @click="loadFireSources(activeScene.id)">重新读取火点</button></div>
          <label for="start-time">起火时间</label><input id="start-time" v-model="parameterForm.start_time" type="time" required/>
          <label for="wind-direction">风向与风力</label><select id="wind-direction" v-model="parameterForm.wind_direction"><option>微风</option><option>东北微风</option><option>北风</option><option>东风</option></select>
        </div>
        <div class="atlas-property-group"><h3>关联与影响</h3><p>{{previewError ? '预览失败，请修复参数后重新计算；暂不显示旧的路径建议。' : preview?.route_advice || '正在计算通道与人员影响…'}}</p><dl><div><dt>风险等级</dt><dd>{{previewError ? '待重新计算' : preview?.risk_level || '—'}}</dd></div><div><dt>烟气等级</dt><dd>{{previewError ? '待重新计算' : preview?.smoke_level || '—'}}</dd></div></dl><small>{{preview?.explanation}}</small></div><button class="primary-button" :disabled="isSaving || !validPreviewParameters()">保存场景参数</button>
       </form>
       <template v-else-if="preparationStep===3"><h2>机器人与任务</h2><p>沿冻结路网巡检，发现火情后触发处置任务。完整训练必须包含案例标准处置，避免无任务场次直接失分。</p><button id="scenario-tasks" class="secondary-button" type="button" :disabled="isSaving || parametersDirty" @click="repairTasks">{{isSaving?'正在补齐…':'补齐案例标准处置任务'}}</button><DecisionEditor :api-base-url="apiBaseUrl" :access-token="accessToken" :key="activeScene.id+'-'+activeVersion?.version_number" :scene-id="activeScene.id" @close="openPreparationStep(1)"/></template>
       <ScenePublishPanel v-else :api-base-url="apiBaseUrl" :access-token="accessToken" :key="activeScene.id+'-'+activeVersion?.version_number" :scene-id="activeScene.id" :scene-status="activeScene.status" :version-number="activeVersion?.version_number ?? 0" @published="handlePublished" @locate="locateIssue"/>
      </aside>
    </section>
    <footer v-if="activeScene" class="atlas-preparation__validation"><AppIcon :name="validation?.passed?'check':'inspect'" :size="23"/><strong>场景校验：</strong><span>{{parametersDirty?'参数未保存，请先保存后校验':validation?validation.passed?'校验通过，可以冻结':validation.issues.length+' 项需处理':'尚未校验当前版本'}}</span><p>{{validation?.issues[0] || (parametersDirty?'三维正在试算，尚未写入场景版本。':'预览与正式演练使用同一份场景数据。')}}</p><button :disabled="validating || parametersDirty" @click="validateCurrent">{{validating?'正在校验…':'运行校验'}}<AppIcon name="arrowRight" :size="17"/></button></footer>
    <ul v-if="validation && !validation.passed" class="configuration-issues"><li v-for="issue in validation.issue_details" :key="issue.key"><span>{{issue.message}}</span><button type="button" @click="locateIssue(issue)">定位修改<AppIcon name="arrowRight" :size="18"/></button></li></ul>
    <UiConfirmDialog :open="discardConfirmationOpen" title="放弃未保存参数" description="当前三维试算尚未写入场景版本。继续离开将丢弃这些参数修改。" confirm-label="放弃修改" danger @cancel="cancelDiscard" @confirm="confirmDiscard"/>
  </main>
</template>
<style scoped>
.atlas-preparation__new-scene{display:flex;align-items:center;justify-content:center;gap:8px;min-height:44px;font-size:16px;border:1px solid var(--border-default);border-radius:var(--radius-sm)}
.atlas-preparation__steps>.atlas-preparation__new-scene::after{display:none}.scenario-unavailable{min-width:0}.scenario-unavailable p{font-size:16px}.scenario-unavailable button{width:100%;min-height:44px;margin-block:8px;white-space:normal}
.atlas-scene-empty{overflow:auto;min-height:0}.atlas-scene-empty h2{font-size:28px;margin:0 0 20px}.atlas-scene-empty form>label{font-size:16px}.atlas-scene-empty form>label input{font-size:16px}
.configuration-location{padding:12px;border:1px solid var(--border-default);color:var(--text-secondary);font-size:16px;line-height:1.6}.configuration-issues{padding:16px 28px;list-style:none;margin:0}.configuration-issues li{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;padding:12px 0;border-bottom:1px solid var(--border-default);font-size:16px}.configuration-issues button{display:flex;align-items:center;gap:8px;min-height:44px;padding:8px 12px;font:inherit;color:var(--text-primary);background:var(--surface-panel);border:1px solid var(--border-default);border-radius:var(--radius-sm)}
</style>
