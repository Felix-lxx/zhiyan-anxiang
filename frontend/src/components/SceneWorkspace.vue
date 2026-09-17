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
    error.value = ''; notice.value = ''; previewError.value = ''
    hydrateParameters(scene)
    void loadPreview(scene.id, !latestVersion(scene)?.parameters.fire_source_object_id)
  })
}
function leaveEditor() {
  guardUnsaved(() => { selectedSceneId.value = ''; activeStep.value = 'parameters'; preview.value = null; error.value = ''; notice.value = ''; previewError.value = ''; parametersDirty.value = false })
}
function toggleComparison(scene: Scene) {
  comparisonSceneId.value = comparisonSceneId.value === scene.id ? '' : scene.id
}
function changeStep(step: WorkflowStep) {
  if (step === 'parameters' || step === 'preview') {
    activeStep.value = step
    if (step === 'preview' && activeScene.value) void loadPreview(activeScene.value.id)
    return
  }
  guardUnsaved(() => {
    activeStep.value = step; error.value = ''; notice.value = ''
  })
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
    const saved = scenes.value.find(scene => scene.id === route.query.scene)
    if (saved) selectScene(saved, workflowSteps.some(step => step.id === route.query.step) ? route.query.step as WorkflowStep : 'parameters')
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
function handleParameterChange() { parametersDirty.value = true; schedulePreview() }
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
watch([selectedSceneId, activeStep], () => {
  if (isLoading.value || route.name !== 'scenes') return
  void router.replace({ query: { ...route.query, scene: selectedSceneId.value || undefined, step: selectedSceneId.value ? activeStep.value : undefined } })
})
onMounted(() => { window.addEventListener('beforeunload', handleBeforeUnload); void load() })
onBeforeUnmount(() => { window.removeEventListener('beforeunload', handleBeforeUnload); if (previewTimer) window.clearTimeout(previewTimer); previewController?.abort() })
</script>

<template>
  <main id="main-content" class="workspace-shell scene-workspace">
    <header class="workspace-header"><button class="workspace-brand workspace-brand--button" type="button" @click="emit('back')">智演安巷</button><button class="text-action icon-action" type="button" @click="emit('back')"><AppIcon name="back" :size="17" />返回社区地图</button></header>
    <section class="workspace-content" aria-labelledby="scene-title">
      <div class="scene-hero"><div><h1 id="scene-title">{{ community.name }} · 演练场景</h1><p>配置结果直接进入三维现场；保存发布后，导演台将冻结并运行同一份社区、路网和人员模型。</p></div><p class="scene-hero__summary">{{ scenes.length }} 个场景 · {{ scenes.filter((scene) => scene.status === 'published').length }} 个已发布</p></div>
      <p v-if="error" class="message message--error" role="alert">{{ error }}</p><p v-if="notice" class="message message--success" role="status">{{ notice }}</p>

      <div v-if="!activeScene" class="scene-overview">
        <section class="scene-library" aria-labelledby="scene-library-title">
          <div class="section-heading"><h2 id="scene-library-title">已有场景</h2><button v-if="error" class="text-action" type="button" @click="load">重新加载</button></div>
          <p v-if="isLoading" class="register-state">正在读取场景草稿…</p>
          <div v-else-if="!scenes.length" class="scene-empty"><AppIcon name="building" :size="28" /><h3>尚未创建场景</h3><p>从右侧模板创建第一份演练场景，随后配置火情和空间规则。</p></div>
          <div v-else class="scene-card-list">
            <article v-for="scene in scenes" :key="scene.id" class="scene-card">
              <div class="scene-card__top"><div><strong>{{ scene.name }}</strong><p>版本 {{ latestVersion(scene)?.version_number ?? 0 }} · {{ latestVersion(scene)?.parameters.start_time || '待设置时间' }}</p></div><span class="status-badge" :data-status="scene.status">{{ scene.status === 'published' ? '已发布' : '草稿' }}</span></div>
              <div class="scene-card__facts"><span><AppIcon name="fire" :size="15" />{{ latestVersion(scene)?.parameters.fire_source_type || '未配置火源' }}</span><span><AppIcon name="users" :size="15" />{{ latestVersion(scene)?.parameters.resident_count || '—' }} 人</span></div>
              <div class="scene-card__actions"><button class="secondary-button" type="button" @click="selectScene(scene)">编辑场景</button><button class="text-action icon-action" type="button" @click="selectScene(scene, 'preview')"><AppIcon name="eye" :size="16" />查看预览</button><button class="text-action icon-action" type="button" :aria-expanded="comparisonSceneId === scene.id" @click="toggleComparison(scene)"><AppIcon name="compare" :size="16" />对比训练</button></div>
            </article>
          </div>
          <TrainingComparison v-if="comparisonScene" :key="comparisonScene.id" :api-base-url="apiBaseUrl" :access-token="accessToken" :scene-id="comparisonScene.id" :scene-name="comparisonScene.name" @close="comparisonSceneId = ''" @open-drill="drillId => emit('openDrill', comparisonScene!.id, drillId)" />
        </section>
        <aside class="scene-create" aria-labelledby="scene-create-title"><div class="section-heading"><h2 id="scene-create-title">新建场景</h2></div><p>从规则模板创建独立草稿，不会覆盖正在运行的演练。</p><form class="map-object-form" @submit.prevent="createScene"><label for="scene-template">场景模板</label><select id="scene-template" v-model="selectedTemplateId" required :disabled="isLoading"><option v-for="template in templates" :key="template.id" :value="template.id">{{ template.name }}</option></select><p v-if="templates.find((item) => item.id === selectedTemplateId)?.description" class="field-hint">{{ templates.find((item) => item.id === selectedTemplateId)?.description }}</p><label for="scene-name">场景名称</label><input id="scene-name" v-model="name" required minlength="2" maxlength="120" placeholder="例如：3 号楼夜间充电棚火灾" /><button class="primary-button icon-button" type="submit" :disabled="isSaving || isLoading || !chargingSheds.length"><AppIcon name="plus" :size="18" />{{ isSaving ? '正在创建…' : '创建场景草稿' }}</button><p v-if="!isLoading && !chargingSheds.length" class="field-warning">当前社区没有充电棚对象，请先返回地图添加。</p></form></aside>
      </div>

      <template v-else>
        <div class="scene-context"><div><button class="text-action icon-action" type="button" @click="leaveEditor"><AppIcon name="back" :size="16" />全部场景</button><h2>{{ activeScene.name }}</h2><p>版本 {{ activeVersion?.version_number ?? 0 }} · <span class="status-badge" :data-status="activeScene.status">{{ activeScene.status === 'published' ? '已发布' : '草稿' }}</span></p></div><p>所有步骤共享当前场景上下文；修改已发布场景会自动派生新草稿版本。</p></div>
        <nav class="workflow-nav" aria-label="场景配置步骤"><button v-for="step in workflowSteps" :key="step.id" type="button" :aria-current="activeStep === step.id ? 'step' : undefined" @click="changeStep(step.id)"><AppIcon :name="step.icon" :size="19" /><span><strong>{{ step.label }}</strong><small>{{ step.helper }}</small></span></button></nav>
        <div class="scene-workflow">
          <section v-if="activeStep === 'parameters'" class="workflow-panel workflow-panel--parameters" aria-labelledby="parameters-title">
            <div class="workflow-panel__intro"><h2 id="parameters-title">基本参数</h2><p>修改任一参数，右侧三维现场会先试算；只有点击保存才写入场景版本。</p></div>
            <div class="parameter-editor-layout">
              <form class="parameter-grid parameter-grid--stacked" @submit.prevent="saveParameters" @input="handleParameterChange" @change="handleParameterChange">
                <label for="fire-source"><span>起火点</span><small>来自当前社区地图的充电棚</small></label><select id="fire-source" v-model="parameterForm.fire_source_object_id" required><option v-for="shed in chargingSheds" :key="shed.id" :value="shed.id">{{ shed.name }}</option></select>
                <label for="start-time"><span>起火时间</span><small>切换三维现场昼夜光照</small></label><input id="start-time" v-model="parameterForm.start_time" type="time" required />
                <label for="wind-direction"><span>风向与风力</span><small>改变三维烟气漂移方向</small></label><select id="wind-direction" v-model="parameterForm.wind_direction"><option>微风</option><option>东北微风</option><option>北风</option><option>东风</option></select>
                <label for="resident-count"><span>参演居民数</span><small>决定冻结人员总量，范围 1–1000</small></label><input id="resident-count" v-model.number="parameterForm.resident_count" type="number" min="1" max="1000" required />
                <label for="stair-width"><span>住宅楼梯净宽</span><small>决定楼梯通行容量和排队速度</small></label><div class="input-with-unit"><input id="stair-width" v-model.number="parameterForm.stair_width" type="number" min="0.6" max="3" step="0.1" required /><span>米</span></div>
                <label for="hydrant-status"><span>东侧消火栓</span><small>影响火势增长和取水策略</small></label><select id="hydrant-status" v-model="parameterForm.hydrant_status"><option value="faulty">故障待替代</option><option value="available">可用</option></select>
                <label for="south-lane-status"><span>南门消防通道</span><small>直接改变路网和疏散可达性</small></label><select id="south-lane-status" v-model="parameterForm.south_lane_status"><option value="restricted">受限</option><option value="open">畅通</option><option value="blocked">阻断</option></select>
                <div class="parameter-actions"><span v-if="previewIsDraft" class="unsaved-indicator">右侧为未保存试算</span><span v-else>当前为已保存版本</span><button class="primary-button icon-button" type="submit" :disabled="isSaving || !validPreviewParameters()"><AppIcon name="check" :size="18" />{{ isSaving ? '正在保存…' : '保存场景参数' }}</button></div>
              </form>
              <SceneLivePreview :simulation="preview?.simulation ?? null" :loading="isPreviewing" :error="previewError" :minute="previewMinute" :draft="previewIsDraft" :fire-level="preview?.fire_level" :smoke-level="preview?.smoke_level" :risk-level="preview?.risk_level" compact />
            </div>
          </section>
          <section v-else-if="activeStep === 'preview'" class="workflow-panel preview-panel" aria-labelledby="preview-title">
            <div class="workflow-panel__intro"><h2 id="preview-title">空间风险预览</h2><p>这是正式演练创建时将被冻结的同一套空间模型。拖动时间查看火烟发展和道路风险。</p></div>
            <div class="preview-workspace">
              <div class="preview-control"><label for="preview-minute">推演时间 <strong>{{ previewMinute }} 分钟</strong></label><input id="preview-minute" v-model.number="previewMinute" type="range" min="0" max="10" @input="handlePreviewMinuteChange" /><div aria-hidden="true"><span>起火</span><span>5 分钟</span><span>10 分钟</span></div></div>
              <SceneLivePreview :simulation="preview?.simulation ?? null" :loading="isPreviewing" :error="previewError" :minute="previewMinute" :draft="previewIsDraft" :fire-level="preview?.fire_level" :smoke-level="preview?.smoke_level" :risk-level="preview?.risk_level" />
              <div v-if="preview" class="preview-findings"><dl><div><dt>冻结居民</dt><dd>{{ preview.simulation.summary.total }} 人</dd></div><div><dt>楼梯净宽</dt><dd>{{ preview.simulation.world.spatial_network.stair_width }} 米</dd></div><div><dt>南门通道</dt><dd>{{ { open: '畅通', restricted: '受限', blocked: '阻断' }[preview.simulation.environment.south_lane] ?? preview.simulation.environment.south_lane }}</dd></div><div><dt>东侧水源</dt><dd>{{ preview.simulation.environment.east_hydrant === 'available' ? '可用' : '故障' }}</dd></div></dl><div><h3>{{ preview.route_advice }}</h3><p>当前受影响：{{ preview.affected_targets.join('、') || '暂无直接影响对象' }}</p><small>{{ preview.explanation }}</small></div></div>
              <button class="secondary-button icon-button preview-retry" type="button" :disabled="isPreviewing" @click="loadPreview(activeScene.id, previewIsDraft)"><AppIcon name="refresh" :size="17" />{{ isPreviewing ? '正在更新…' : '重新计算' }}</button>
            </div>
          </section>
          <DecisionEditor v-else-if="activeStep === 'decisions'" :api-base-url="apiBaseUrl" :access-token="accessToken" :key="activeScene.id" :scene-id="activeScene.id" @close="changeStep('parameters')" />
          <ScenePublishPanel v-else :api-base-url="apiBaseUrl" :access-token="accessToken" :key="activeScene.id" :scene-id="activeScene.id" :scene-status="activeScene.status" :version-number="activeVersion?.version_number ?? 0" @published="handlePublished" />
        </div>
      </template>
    </section>
    <UiConfirmDialog :open="discardConfirmationOpen" title="放弃未保存参数" description="当前三维试算尚未写入场景版本。继续离开将丢弃这些参数修改。" confirm-label="放弃修改" danger @cancel="cancelDiscard" @confirm="confirmDiscard" />
  </main>
</template>

<style scoped>
.scene-workspace{min-height:100vh;background:#f3f1e9}.scene-workspace .workspace-content{width:min(100% - 3rem,88rem);margin:0 auto;padding:2.8rem 0 5rem}.icon-action,.icon-button{display:inline-flex;align-items:center;justify-content:center;gap:.45rem}.scene-hero{display:flex;align-items:end;justify-content:space-between;gap:3rem;padding:1.5rem 0 2.2rem;border-bottom:1px solid #aab5b0}.scene-eyebrow,.section-heading span,.workflow-panel__intro>span{color:#a24d35;font-size:.7rem;font-weight:750;letter-spacing:.14em}.scene-hero h1{max-width:48rem;margin:.65rem 0 0;color:#172323;font-size:clamp(2.4rem,5vw,4.8rem);line-height:.98;letter-spacing:-.055em}.scene-hero p{max-width:48rem;margin:1rem 0 0;color:#596464;line-height:1.7}.scene-hero__stat{display:grid;grid-template-columns:auto auto;gap:.15rem .7rem;min-width:11rem;border-top:2px solid #164b49;padding-top:.75rem}.scene-hero__stat strong{color:#123b3c;font-size:1.65rem;line-height:1}.scene-hero__stat span{align-self:center;color:#71807d;font-size:.78rem}
.scene-overview{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(19rem,.55fr);gap:clamp(2rem,5vw,5rem);padding-top:2rem}.section-heading{display:flex;align-items:start;justify-content:space-between;gap:1rem;border-top:2px solid #173f3e;padding-top:.8rem}.section-heading h2{margin:.3rem 0 0;color:#1e2928;font-size:1.35rem}.scene-card-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem;margin-top:1.25rem}.scene-card{display:grid;gap:1.15rem;min-height:13.5rem;border:1px solid #c6cfca;border-radius:1rem;background:#faf9f4;padding:1.15rem;transition:border-color 160ms ease,transform 160ms ease,box-shadow 160ms ease}.scene-card:hover{border-color:#78908a;transform:translateY(-2px);box-shadow:0 14px 28px rgb(25 54 52 / 9%)}.scene-card__top{display:flex;align-items:start;justify-content:space-between;gap:1rem}.scene-card__top strong{color:#1e2928;font-size:1rem}.scene-card__top p{margin:.35rem 0 0;color:#71807d;font-size:.76rem}.status-badge{display:inline-flex;width:fit-content;border:1px solid #c79c7f;border-radius:999px;background:#fbede4;color:#8a351f;padding:.22rem .5rem;font-size:.68rem;white-space:nowrap}.status-badge[data-status="published"]{border-color:#8eb4a1;background:#e4f4ec;color:#14543f}.scene-card__facts{display:flex;align-items:center;gap:1rem;flex-wrap:wrap;color:#596464;font-size:.76rem}.scene-card__facts span{display:inline-flex;align-items:center;gap:.35rem}.scene-card__actions{display:flex;align-items:center;justify-content:space-between;gap:1rem;margin-top:auto}.scene-card__actions .secondary-button{min-height:2.55rem;margin:0;padding:0 .85rem}.scene-create{align-self:start;border-radius:1rem;background:#e8ece5;padding:1.15rem}.scene-create>p{margin:1rem 0 0;color:#596464;font-size:.82rem;line-height:1.65}.field-hint,.field-warning{margin:-.25rem 0 .2rem;color:#71807d;font-size:.73rem;line-height:1.55}.field-warning{color:#8a351f}.scene-empty{display:grid;justify-items:start;gap:.5rem;margin-top:1.2rem;border:1px dashed #aeb8b5;border-radius:1rem;padding:2rem;color:#46605b}.scene-empty h3,.scene-empty p{margin:0}.scene-empty p{color:#71807d;font-size:.82rem}
.scene-context{display:flex;align-items:end;justify-content:space-between;gap:2rem;margin-top:2rem}.scene-context h2{margin:.55rem 0 .25rem;color:#1e2928;font-size:1.65rem}.scene-context p{max-width:32rem;margin:0;color:#71807d;font-size:.78rem;line-height:1.55}.scene-context .status-badge{margin-left:.2rem;vertical-align:middle}.workflow-nav{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));margin-top:1.5rem;border:1px solid #b9c3be;border-radius:1rem;overflow:hidden;background:#faf9f4}.workflow-nav button{display:grid;grid-template-columns:auto auto 1fr;align-items:center;gap:.65rem;min-height:5rem;border:0;border-right:1px solid #d2d8d4;background:transparent;color:#65736f;padding:.85rem 1rem;text-align:left}.workflow-nav button:last-child{border-right:0}.workflow-nav button:hover{background:#eef1eb}.workflow-nav button[aria-current="step"]{background:#173f3e;color:#f8f5ec}.workflow-nav__index{font-size:.65rem;font-weight:750;letter-spacing:.08em;opacity:.6}.workflow-nav strong,.workflow-nav small{display:block}.workflow-nav strong{font-size:.82rem}.workflow-nav small{margin-top:.18rem;color:inherit;font-size:.65rem;opacity:.72}.scene-workflow{margin-top:1rem;border:1px solid #c5cdc9;border-radius:1rem;background:#faf9f4;overflow:hidden}.workflow-panel{display:grid;grid-template-columns:minmax(13rem,.38fr) minmax(0,1fr);gap:clamp(2rem,5vw,5rem);padding:clamp(1.25rem,3vw,2.2rem)}.workflow-panel__intro{align-self:start;border-top:2px solid #a24d35;padding-top:.8rem}.workflow-panel__intro h2{margin:.45rem 0 0;color:#1d2928;font-size:1.65rem}.workflow-panel__intro p{margin:.7rem 0 0;color:#71807d;font-size:.8rem;line-height:1.65}
.parameter-grid{display:grid;grid-template-columns:minmax(10rem,.7fr) minmax(13rem,1fr);align-items:center;gap:.75rem 1.25rem}.parameter-grid label{display:grid;gap:.18rem;color:#334040}.parameter-grid label span{font-size:.82rem;font-weight:700}.parameter-grid label small{color:#81908c;font-size:.68rem;font-weight:500}.parameter-grid input,.parameter-grid select{width:100%;min-height:2.85rem;border:1px solid #aeb8b5;border-radius:.72rem;background:#fff;color:#1e2626;padding:.65rem .78rem}.parameter-grid input:focus,.parameter-grid select:focus{border-color:#1c5d5b;box-shadow:0 0 0 3px rgb(28 93 91 / 11%)}.input-with-unit{position:relative}.input-with-unit span{position:absolute;top:50%;right:.75rem;color:#71807d;font-size:.74rem;transform:translateY(-50%)}.input-with-unit input{padding-right:2.5rem}.parameter-actions{grid-column:1/-1;display:flex;align-items:center;justify-content:flex-end;gap:1rem;border-top:1px solid #d5dbd7;margin-top:.5rem;padding-top:1rem}.parameter-actions .primary-button{min-width:12rem;margin:0}.unsaved-indicator{color:#a24d35;font-size:.73rem;font-weight:650}
.preview-control{grid-column:2}.preview-control label{display:flex;justify-content:space-between;color:#465251;font-size:.78rem}.preview-control input{width:100%;margin-top:.8rem;accent-color:#a24d35}.preview-control>div{display:flex;justify-content:space-between;color:#89948f;font-size:.64rem}.preview-result{grid-column:2;display:grid;grid-template-columns:8.5rem 1fr;gap:1rem}.risk-orbit{grid-row:span 2;display:grid;place-content:center;aspect-ratio:1;border:1px solid #bd715d;border-radius:50%;background:#fae8df;color:#7d2e1b;text-align:center}.risk-orbit strong,.risk-orbit small,.risk-orbit span{display:block}.risk-orbit strong{font-size:2rem}.risk-orbit span,.risk-orbit small{font-size:.68rem}.risk-orbit[data-risk="关注"]{border-color:#7ba78f;background:#e4f4ec;color:#14543f}.preview-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border-top:1px solid #aeb8b5}.preview-metrics div{border-right:1px solid #d5dbd7;padding:.75rem}.preview-metrics div:last-child{border-right:0}.preview-metrics span,.preview-metrics strong{display:block}.preview-metrics span{color:#71807d;font-size:.67rem}.preview-metrics strong{margin-top:.3rem;color:#293534;font-size:.85rem}.preview-brief{border-top:1px solid #d5dbd7;padding-top:.8rem}.preview-brief>span{color:#a24d35;font-size:.67rem;font-weight:750}.preview-brief h3{margin:.35rem 0 0;font-size:.95rem}.preview-brief p,.preview-brief small{display:block;margin:.45rem 0 0;color:#71807d;font-size:.72rem;line-height:1.6}.preview-panel>.secondary-button{grid-column:2;justify-self:end;min-height:2.7rem;margin:0}.preview-empty{grid-column:2;border:1px dashed #b8c2bd;border-radius:.8rem;padding:2rem;color:#71807d;text-align:center}
.scene-workspace .scene-hero{align-items:center;padding:1.2rem 0 1.5rem}
.scene-workspace .scene-hero h1{margin:0;font-size:2.15rem;line-height:1.15;letter-spacing:-.025em}
.scene-hero__summary{flex:0 0 auto;margin:0!important;border-top:1px solid #82928d;padding-top:.55rem;color:#596b66!important;font-size:.76rem}
.section-heading h2{margin:0}
.workflow-nav button{grid-template-columns:auto 1fr;min-height:4.25rem}
.workflow-panel{grid-template-columns:minmax(10rem,.25fr) minmax(0,1fr);gap:2rem;padding:1.5rem}
.workflow-panel__intro{border-top-color:#315f57}
.workflow-panel__intro h2{margin:.35rem 0 0;font-size:1.35rem}
.parameter-editor-layout{grid-column:2;display:grid;grid-template-columns:minmax(19rem,22rem) minmax(0,1fr);gap:1rem;align-items:start;min-width:0}
.parameter-grid--stacked{grid-template-columns:1fr;align-content:start;border-right:1px solid #d5dbd7;padding-right:1rem}
.parameter-grid--stacked label{margin-top:.2rem}
.parameter-grid--stacked .parameter-actions{grid-column:1;justify-content:space-between;flex-wrap:wrap}
.parameter-actions>span:not(.unsaved-indicator){color:#71807d;font-size:.72rem}
.parameter-grid--stacked .primary-button{min-width:0}
.preview-workspace{grid-column:2;display:grid;gap:1rem;min-width:0}
.preview-workspace .preview-control{grid-column:auto}
.preview-findings{display:grid;grid-template-columns:minmax(19rem,.7fr) minmax(0,1fr);gap:1.25rem;border-top:1px solid #d5dbd7;padding-top:1rem}
.preview-findings dl{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));margin:0}
.preview-findings dl div{border-right:1px solid #d5dbd7;padding:0 .75rem}
.preview-findings dl div:first-child{padding-left:0}.preview-findings dl div:last-child{border-right:0}
.preview-findings dt{color:#71807d;font-size:.66rem}.preview-findings dd{margin:.28rem 0 0;color:#243532;font-size:.8rem;font-weight:700}
.preview-findings>div{min-width:0}.preview-findings h3{margin:0;color:#22322f;font-size:.92rem}.preview-findings p,.preview-findings small{display:block;margin:.4rem 0 0;color:#667772;font-size:.7rem;line-height:1.55;overflow-wrap:anywhere}
.preview-retry{justify-self:end;min-height:2.55rem;margin:0}
.scene-card:hover{transform:none;box-shadow:none}
.scene-card-list{grid-template-columns:1fr;gap:0;border-top:1px solid #c6cfca}
.scene-card{grid-template-columns:minmax(0,1.2fr) minmax(10rem,.75fr) auto;align-items:center;min-height:6.5rem;border:0;border-bottom:1px solid #c6cfca;border-radius:0;background:transparent;padding:1rem .2rem;transition:background-color 160ms ease}
.scene-card:hover{background:color-mix(in srgb,#faf9f4 72%,#e8ece5)}
.scene-card__facts{align-self:center}
.scene-card__actions{justify-content:flex-end;margin-top:0}
.scene-create{border:1px solid #d0d8d1;border-top:2px solid #173f3e;box-shadow:0 12px 24px rgb(25 54 52 / 6%)}
.scene-workspace h1,.scene-workspace h2,.scene-workspace h3,.scene-workspace strong{text-wrap:balance}
.scene-workspace .workspace-header{min-height:64px;border-bottom-color:#315850;background:#103d37;color:#eef5f1}.scene-workspace .workspace-brand,.scene-workspace .workspace-header .text-action{color:#eef5f1}.scene-workspace .workspace-header .text-action:hover{background:#194f47}.scene-workspace{background:#e7e9e4}.scene-workspace .workspace-content{width:min(calc(100% - 2rem),96rem);padding-top:1.25rem}.scene-workspace .scene-hero{padding:.7rem 0 1.1rem}.scene-workspace .scene-hero h1{font-size:1.75rem}.scene-workspace .scene-hero__summary{max-width:24rem}.workflow-nav{margin-top:1rem;border-radius:8px}.workflow-nav button{min-height:3.8rem}.scene-workflow{border-radius:8px}.workflow-panel{grid-template-columns:220px minmax(0,1fr);gap:1.25rem;padding:1.1rem}.parameter-editor-layout{grid-template-columns:300px minmax(0,1fr)}.scene-live-preview{border-radius:8px}.scene-live-preview--large .scene-live-preview__viewport{height:min(64vh,42rem);min-height:34rem}
@media(max-width:1100px){.parameter-editor-layout{grid-template-columns:1fr}.parameter-grid--stacked{grid-template-columns:minmax(10rem,.7fr) minmax(13rem,1fr);border-right:0;border-bottom:1px solid #d5dbd7;padding-right:0;padding-bottom:1rem}.parameter-grid--stacked .parameter-actions{grid-column:1/-1}}
@media(max-width:900px){.scene-overview,.workflow-panel{grid-template-columns:1fr}.scene-card-list{grid-template-columns:1fr}.scene-card{grid-template-columns:minmax(0,1fr) auto;gap:.75rem 1rem}.scene-card__facts{grid-column:1/-1}.scene-card__actions{grid-column:2;grid-row:1;align-self:start}.workflow-nav{grid-template-columns:repeat(2,1fr)}.workflow-nav button:nth-child(2){border-right:0}.workflow-nav button:nth-child(-n+2){border-bottom:1px solid #d2d8d4}.parameter-editor-layout,.preview-workspace,.preview-control,.preview-result,.preview-panel>.secondary-button,.preview-empty{grid-column:1}.preview-findings{grid-template-columns:1fr}}
@media(max-width:640px){.scene-workspace .workspace-content{width:min(100% - 1.5rem,88rem);padding-top:1.4rem}.scene-hero,.scene-context{align-items:start;flex-direction:column;gap:1rem}.scene-workspace .scene-hero h1{font-size:1.65rem}.scene-hero__summary{align-self:stretch}.workflow-nav button{min-height:3.8rem;padding:.6rem}.workflow-nav small{display:none}.workflow-panel{padding:.85rem}.parameter-grid,.parameter-grid--stacked{grid-template-columns:1fr}.parameter-grid input,.parameter-grid select{font-size:1rem}.parameter-actions,.parameter-grid--stacked .parameter-actions{grid-column:1;align-items:stretch;flex-direction:column}.preview-findings dl{grid-template-columns:repeat(2,1fr);gap:.8rem 0}.preview-findings dl div:nth-child(2){border-right:0}.preview-result{grid-template-columns:1fr}.preview-metrics{grid-template-columns:repeat(2,1fr)}.preview-metrics div:nth-child(2){border-right:0}}

/* Layout pass: one clear reading column with a stable action rail. */
.scene-workspace .workspace-content { width: min(calc(100% - clamp(2rem, 6vw, 7rem)), 82rem); padding-top: clamp(2rem, 4vw, 3.5rem); }
.scene-hero { max-width: 82rem; }
.scene-hero > div { min-width: 0; }
.scene-hero__summary { max-width: 12rem; line-height: 1.5; }
.scene-overview { grid-template-columns: minmax(0, 1fr) minmax(19rem, 22rem); align-items: start; gap: clamp(2rem, 4vw, 4rem); }
.scene-library { min-width: 0; }
.scene-card__top > div { min-width: 0; }
.scene-card__top strong { display: block; overflow-wrap: anywhere; }
.scene-card__facts { justify-content: flex-start; }
.scene-create { position: sticky; top: 1.25rem; }
.workflow-nav { position: sticky; top: .75rem; z-index: 2; }
.workflow-nav button { min-width: 0; }
.workflow-nav strong, .workflow-nav small { overflow-wrap: anywhere; }
.scene-workflow { min-width: 0; }
.workflow-panel > * { min-width: 0; }
.parameter-editor-layout, .preview-workspace { min-width: 0; }

@media (max-width: 1100px) {
  .scene-create { position: static; }
  .workflow-nav { top: .5rem; }
}

@media (max-width: 900px) {
  .scene-overview { grid-template-columns: minmax(0, 1fr); }
  .scene-library, .scene-create { min-width: 0; }
  .scene-card { grid-template-columns: minmax(0, 1fr); align-items: start; }
  .scene-card__facts, .scene-card__actions { grid-column: 1; grid-row: auto; }
  .scene-card__actions { justify-content: flex-start; flex-wrap: wrap; }
}

@media (max-width: 640px) {
  .scene-workspace .workspace-content { width: min(calc(100% - 1.5rem), 82rem); padding-top: 1.4rem; }
  .workflow-nav { position: static; }
  .scene-card__top { align-items: start; }
  .scene-card__actions { min-width: 0; }
  .scene-card__actions > * { flex: 1 1 auto; }
}
</style>
