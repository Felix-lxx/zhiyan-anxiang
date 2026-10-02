<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import type { Community, MapObjectSummary, Scene } from '../domain/models'
import AppIcon from './AppIcon.vue'
import DecisionEditor from './DecisionEditor.vue'
import ScenePublishPanel from './ScenePublishPanel.vue'
import SceneLivePreview from './SceneLivePreview.vue'
import TrainingComparison from './TrainingComparison.vue'
import UiConfirmDialog from './ui/UiConfirmDialog.vue'
import '../scene-preview.css'
import '../atlas-scene.css'
import { createApiClient } from '../api/client'

interface Template { id: string; name: string; description: string; defaults: Record<string, string> }
interface Preview {
  fire_level: string; smoke_level: string; risk_level: string; affected_targets: string[]; route_advice: string; explanation: string
  simulation: Record<string, unknown> & { summary: { total: number; congested?: number; smoke_exposed?: number }; environment: { east_hydrant: string; south_lane: string; visibility?: number }; world: { parameters: Record<string, unknown>; spatial_network: { stair_width: number } } }
}
type WorkflowStep = 'parameters' | 'preview' | 'decisions' | 'publish'

const props = defineProps<{ apiBaseUrl: string; accessToken: string; community: Community }>()
const emit = defineEmits<{ back: []; openDrill: [sceneId: string, drillId: string] }>()
const api = createApiClient(props.apiBaseUrl, () => props.accessToken)
const route = useRoute(), router = useRouter()
const templates = ref<Template[]>([])
const scenes = ref<Scene[]>([])
const chargingSheds = ref<MapObjectSummary[]>([])
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
const parameterForm = ref({ fire_source_object_id: '', start_time: '20:15', wind_direction: '微风', resident_count: 60, hydrant_status: 'faulty', south_lane_status: 'restricted', stair_width: 1.2 })
const previewMinute = ref(0)
const preparationStep = ref(1)
const validation = ref<{ passed: boolean; issues: string[]; message?: string } | null>(null)
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
const activeVersion = computed(() => activeScene.value ? latestVersion(activeScene.value) : null)
const comparisonScene = computed(() => scenes.value.find(scene => scene.id === comparisonSceneId.value) ?? null)
const previewIsDraft = computed(() => parametersDirty.value || !activeVersion.value?.parameters.fire_source_object_id)
const workflowSteps: Array<{ id: WorkflowStep; label: string; helper: string; icon: string }> = [
  { id: 'parameters', label: '基本参数', helper: '定义火情与资源', icon: 'fire' },
  { id: 'preview', label: '空间预览', helper: '验证风险变化', icon: 'eye' },
  { id: 'decisions', label: '决策任务', helper: '编排处置分支', icon: 'split' },
  { id: 'publish', label: '校验发布', helper: '冻结可运行版本', icon: 'check' },
]

function latestVersion(scene: Scene) { return scene.versions[scene.versions.length - 1] ?? null }
function guardUnsaved(action: () => void) {
  if (!parametersDirty.value) { action(); return }
  pendingDiscardAction = action
  discardConfirmationOpen.value = true
}
function confirmDiscard() {
  if (activeScene.value) hydrateParameters(activeScene.value)
  parametersDirty.value = false
  discardConfirmationOpen.value = false
  const action = pendingDiscardAction
  pendingDiscardAction = null
  action?.()
  resolveLeave?.(true); resolveLeave = null
}
function cancelDiscard() { discardConfirmationOpen.value = false; pendingDiscardAction = null; resolveLeave?.(false); resolveLeave = null }
onBeforeRouteLeave(() => {
  if (!parametersDirty.value) return true
  discardConfirmationOpen.value = true
  return new Promise<boolean>(resolve => { resolveLeave = resolve })
})
function hydrateParameters(scene: Scene) {
  const p = latestVersion(scene)?.parameters ?? {}
  parameterForm.value = {
    fire_source_object_id: String(p.fire_source_object_id ?? chargingSheds.value[0]?.id ?? ''), start_time: String(p.start_time ?? '20:15'), wind_direction: String(p.wind_direction ?? '微风'), resident_count: Number(p.resident_count ?? 60), hydrant_status: String(p.hydrant_status ?? 'faulty'), south_lane_status: String(p.south_lane_status ?? 'restricted'), stair_width: Number(p.stair_width ?? 1.2),
  }
  parametersDirty.value = false
}
function selectScene(scene: Scene, step: WorkflowStep = 'parameters') {
  guardUnsaved(() => {
    if (selectedSceneId.value !== scene.id) { preview.value = null; previewRequest += 1 }
    selectedSceneId.value = scene.id
    activeStep.value = step
    preparationStep.value = step === 'publish' ? 4 : step === 'decisions' ? 3 : 1
    validation.value = null
    error.value = ''; notice.value = ''; previewError.value = ''
    hydrateParameters(scene)
    void loadPreview(scene.id, !latestVersion(scene)?.parameters.fire_source_object_id)
  })
}
function toggleComparison(scene: Scene) {
  comparisonSceneId.value = comparisonSceneId.value === scene.id ? '' : scene.id
}

async function load() {
  isLoading.value = true; error.value = ''
  try {
    const [ta, sb, objects] = await Promise.all([
      api.get<Template[]>('/scene-templates'), api.get<Scene[]>(`/communities/${props.community.id}/scenes`), api.get<MapObjectSummary[]>(`/communities/${props.community.id}/map-objects`),
    ])
    templates.value = ta; scenes.value = sb; chargingSheds.value = objects.filter((item) => item.object_type === 'charging_shed')
    if (!selectedTemplateId.value && templates.value[0]) selectedTemplateId.value = templates.value[0].id
    if (!parameterForm.value.fire_source_object_id && chargingSheds.value[0]) parameterForm.value.fire_source_object_id = chargingSheds.value[0].id
    const saved = scenes.value.find(scene => scene.id === route.query.scene) ?? scenes.value[0]
    if (saved) { selectScene(saved, workflowSteps.some(step => step.id === route.query.step) ? route.query.step as WorkflowStep : 'parameters'); const tab=Number(route.query.preparation); if(route.query.preparation!==undefined&&Number.isInteger(tab)&&tab>=0&&tab<=4)preparationStep.value=tab }
  } catch (caught) { error.value = caught instanceof Error ? caught.message : '场景工作台加载失败。' } finally { isLoading.value = false }
}
async function createScene() {
  error.value = ''; notice.value = ''; isSaving.value = true
  try {
    const scene = await api.post<Scene>(`/communities/${props.community.id}/scenes`, { template_id: selectedTemplateId.value, name: name.value.trim() })
    scenes.value = [scene, ...scenes.value]; name.value = ''; selectScene(scene); notice.value = '场景草稿已创建，请核对并保存基本参数。'
  } catch (caught) { error.value = caught instanceof Error ? caught.message : '场景草稿创建失败。' } finally { isSaving.value = false }
}
async function saveParameters() {
  if (!activeScene.value) return
  const previousVersion = activeVersion.value?.version_number ?? 0
  error.value = ''; notice.value = ''; isSaving.value = true
  try {
    const updated = await api.patch<Scene>(`/scenes/${activeScene.value.id}/charging-shed-parameters`, parameterForm.value)
    scenes.value = scenes.value.map((scene) => scene.id === updated.id ? updated : scene)
    const createdDraft = (latestVersion(updated)?.version_number ?? 0) > previousVersion
    parametersDirty.value = false; notice.value = createdDraft ? '已从发布版本派生新草稿，正在校验空间预览。' : '参数已保存，正在校验空间预览。'; activeStep.value = 'preview'
    await loadPreview(updated.id)
  } catch (caught) { error.value = caught instanceof Error ? caught.message : '参数保存失败。' } finally { isSaving.value = false }
}
function validPreviewParameters(): boolean {
  const value = parameterForm.value
  return Boolean(value.fire_source_object_id && /^([01]\d|2[0-3]):[0-5]\d$/.test(value.start_time) && value.resident_count >= 1 && value.resident_count <= 1000 && value.stair_width >= .6 && value.stair_width <= 3)
}
function schedulePreview() {
  if (previewTimer) window.clearTimeout(previewTimer)
  if (!activeScene.value || !validPreviewParameters()) {
    previewRequest++; previewController?.abort(); isPreviewing.value = false
    previewError.value = activeScene.value ? '请检查起火点、时间、人数和楼梯宽度。' : ''
    return
  }
  previewTimer = window.setTimeout(() => void loadPreview(activeScene.value!.id, true), 360)
}
function handleParameterChange() { parametersDirty.value = true; validation.value = null; schedulePreview() }
function handlePreviewMinuteChange() {
  if (!activeScene.value) return
  if (previewTimer) window.clearTimeout(previewTimer)
  previewTimer = window.setTimeout(() => void loadPreview(activeScene.value!.id, previewIsDraft.value), 180)
}
async function loadPreview(sceneId: string, draft = previewIsDraft.value) {
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
function handleBeforeUnload(event: BeforeUnloadEvent) { if (parametersDirty.value) event.preventDefault() }
watch([selectedSceneId, activeStep, preparationStep], () => {
  if (isLoading.value || route.name !== 'scenes') return
  void router.replace({ query: { ...route.query, scene: selectedSceneId.value || undefined, step: selectedSceneId.value ? activeStep.value : undefined, preparation: selectedSceneId.value ? String(preparationStep.value) : undefined } })
})
onMounted(() => { window.addEventListener('beforeunload', handleBeforeUnload); void load() })
onBeforeUnmount(() => { window.removeEventListener('beforeunload', handleBeforeUnload); if (previewTimer) window.clearTimeout(previewTimer); previewController?.abort() })
</script>

<template>
  <main id="main-content" class="atlas-preparation">
    <header class="atlas-preparation__bar"><button @click="router.push('/projects')"><AppIcon name="building" :size="28"/><strong>智演安巷</strong><span>老旧小区消防应急演练平台</span></button><nav><button aria-current="page">场景准备</button><button :disabled="!activeScene || activeScene.status !== 'published'" @click="router.push({name:'operations',params:{communityId:community.id},query:{scene:activeScene?.id,autostart:'1'}})">演练推演</button><button @click="router.push({name:'projects',query:{section:'history'}})">过程复盘</button><button @click="openMapEditor">资源管理</button></nav><span>{{community.name.split(' · ')[0]}}</span></header>
    <header class="atlas-preparation__heading"><h1>场景准备</h1><span class="atlas-preparation__breadcrumb">{{community.name}} / {{activeScene?.name || '创建场景'}}</span><span v-if="activeScene" class="status-badge" :data-status="activeScene.status">{{parametersDirty ? '未保存' : activeScene.status==='published'?'已发布':'草稿'}}</span><div v-if="activeScene"><button class="secondary-button" :disabled="isSaving || !validPreviewParameters()" @click="saveParameters"><AppIcon name="check" :size="17"/>{{isSaving?'保存中…':'保存草稿'}}</button><button class="primary-button" @click="openPreparationStep(4)"><AppIcon name="lock" :size="17"/>冻结场景</button></div></header>
    <p v-if="error" class="message message--error" role="alert">{{error}}</p><p v-if="notice" class="atlas-preparation__notice" role="status">{{notice}}</p>
    <section v-if="!activeScene" class="atlas-scene-empty"><h2>{{isLoading?'正在读取场景…':'创建演练场景'}}</h2><form v-if="!isLoading" @submit.prevent="createScene"><label>场景模板<select v-model="selectedTemplateId"><option v-for="t in templates" :key="t.id" :value="t.id">{{t.name}}</option></select></label><label>场景名称<input v-model="name" required minlength="2" maxlength="120" placeholder="夜间充电棚火灾"/></label><button class="primary-button" :disabled="isSaving || !chargingSheds.length">创建场景草稿</button><button type="button" class="secondary-button" @click="openMapEditor">编辑社区底图</button><p v-if="!chargingSheds.length">请先在社区底图添加充电棚。</p></form></section>
    <section v-else class="atlas-preparation__workspace">
      <nav class="atlas-preparation__steps" aria-label="场景配置步骤"><button v-for="(step,i) in preparationSteps" :key="step[0]" :aria-current="preparationStep===i?'step':undefined" @click="openPreparationStep(i)"><b>{{i+1}}</b><span><strong>{{step[0]}}</strong><small>{{step[1]}}</small></span></button><label>当前场景<select :value="selectedSceneId" @change="selectScene(scenes.find(s=>s.id===($event.target as HTMLSelectElement).value)!)"><option v-for="s in scenes" :key="s.id" :value="s.id">{{s.name}}</option></select></label></nav>
      <div class="atlas-preparation__canvas"><SceneLivePreview :simulation="preview?.simulation ?? null" :loading="isPreviewing" :error="previewError" :minute="previewMinute" :draft="previewIsDraft" :fire-level="preview?.fire_level" :smoke-level="preview?.smoke_level" :risk-level="preview?.risk_level"/><div class="atlas-preparation__preview-time"><AppIcon name="clock" :size="17"/><label for="preview-minute">推演时刻 {{previewMinute}} 分钟</label><input id="preview-minute" v-model.number="previewMinute" type="range" min="0" max="10" @input="handlePreviewMinuteChange"/><button :disabled="isPreviewing" aria-label="重新计算预览" @click="loadPreview(activeScene.id)"><AppIcon name="refresh" :size="17"/></button></div></div>
      <aside class="atlas-preparation__inspector">
       <template v-if="preparationStep===0"><h2>社区底图</h2><p>楼栋、道路、消防设施与集合点</p><div class="atlas-property-group"><h3>当前社区</h3><strong>{{community.name}}</strong><p>{{community.address || '尚未填写地址'}}</p><button class="primary-button" @click="openMapEditor">打开地图编辑器</button></div><div class="atlas-property-group"><h3>场景关联</h3><p>保存后的社区坐标和路网进入当前三维预览；发布时冻结为运行版本。</p><button class="secondary-button" @click="toggleComparison(activeScene)">方案对比</button><TrainingComparison v-if="comparisonScene" :key="comparisonScene.id" :api-base-url="apiBaseUrl" :access-token="accessToken" :scene-id="comparisonScene.id" :scene-name="comparisonScene.name" @close="comparisonSceneId=''" @open-drill="id=>emit('openDrill',activeScene!.id,id)"/></div></template>
       <form v-else-if="preparationStep===1 || preparationStep===2" class="atlas-properties" @submit.prevent="saveParameters" @input="handleParameterChange" @change="handleParameterChange"><h2>{{preparationStep===1?'人员与南侧通道':'火源与烟气'}}</h2><p>{{preparationStep===1?'配置居民规模、楼梯容量与疏散条件':'配置起火点、时刻和环境条件'}}</p>
        <div v-if="preparationStep===1" class="atlas-property-group"><h3>基本信息</h3><label for="resident-count">参演居民数 <span>人</span></label><input id="resident-count" v-model.number="parameterForm.resident_count" type="number" min="1" max="1000" required/><label for="stair-width">楼梯净宽 <span>米</span></label><input id="stair-width" v-model.number="parameterForm.stair_width" type="number" min=".6" max="3" step=".1" required/><label for="south-lane-status">当前通道状态</label><select id="south-lane-status" v-model="parameterForm.south_lane_status"><option value="open">畅通</option><option value="restricted">受限</option><option value="blocked">阻断</option></select><label for="hydrant-status">东侧消火栓</label><select id="hydrant-status" v-model="parameterForm.hydrant_status"><option value="available">可用</option><option value="faulty">故障待替代</option></select></div>
        <div v-else class="atlas-property-group"><h3>基本信息</h3><label for="fire-source">起火点</label><select id="fire-source" v-model="parameterForm.fire_source_object_id" required><option v-for="shed in chargingSheds" :key="shed.id" :value="shed.id">{{shed.name}}</option></select><label for="start-time">起火时间</label><input id="start-time" v-model="parameterForm.start_time" type="time" required/><label for="wind-direction">风向与风力</label><select id="wind-direction" v-model="parameterForm.wind_direction"><option>微风</option><option>东北微风</option><option>北风</option><option>东风</option></select></div>
        <div class="atlas-property-group"><h3>关联与影响</h3><p>{{preview?.route_advice || '正在计算通道与人员影响…'}}</p><dl><div><dt>风险等级</dt><dd>{{preview?.risk_level || '—'}}</dd></div><div><dt>烟气等级</dt><dd>{{preview?.smoke_level || '—'}}</dd></div></dl><small>{{preview?.explanation}}</small></div><button class="primary-button" :disabled="isSaving || !validPreviewParameters()">保存场景参数</button>
       </form>
       <template v-else-if="preparationStep===3"><h2>机器人与任务</h2><p>沿冻结路网巡检，发现火情后触发处置任务。</p><DecisionEditor :api-base-url="apiBaseUrl" :access-token="accessToken" :key="activeScene.id" :scene-id="activeScene.id" @close="openPreparationStep(1)"/></template>
       <ScenePublishPanel v-else :api-base-url="apiBaseUrl" :access-token="accessToken" :key="activeScene.id+'-'+activeVersion?.version_number" :scene-id="activeScene.id" :scene-status="activeScene.status" :version-number="activeVersion?.version_number ?? 0" @published="handlePublished"/>
      </aside>
    </section>
    <footer v-if="activeScene" class="atlas-preparation__validation"><AppIcon :name="validation?.passed?'check':'inspect'" :size="23"/><strong>场景校验：</strong><span>{{parametersDirty?'参数未保存，请先保存后校验':validation?validation.passed?'校验通过，可以冻结':validation.issues.length+' 项需处理':'尚未校验当前版本'}}</span><p>{{validation?.issues[0] || (parametersDirty?'三维正在试算，尚未写入场景版本。':'预览与正式演练使用同一份场景数据。')}}</p><button :disabled="validating || parametersDirty" @click="validateCurrent">{{validating?'正在校验…':'运行校验'}}<AppIcon name="arrowRight" :size="17"/></button></footer>
    <UiConfirmDialog :open="discardConfirmationOpen" title="放弃未保存参数" description="当前三维试算尚未写入场景版本。继续离开将丢弃这些参数修改。" confirm-label="放弃修改" danger @cancel="cancelDiscard" @confirm="confirmDiscard"/>
  </main>
</template>
