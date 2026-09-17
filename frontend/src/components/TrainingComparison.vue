<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { createApiClient } from '../api/client'
import AppIcon from './AppIcon.vue'
import UiButton from './ui/UiButton.vue'

interface DrillRecord {
  id: string
  name: string
  ended_at: string | null
  elapsed_seconds: number
  score: number
  score_details: Array<{ name: string; score: number; max_score: number; evidence: string }>
  recommendations: string[]
  summary: { total: number | null; evacuated: number | null; counted: number | null; smoke_exposed: number | null; missing: number | null; congested: number | null }
  tasks: { completed: number; total: number }
  evidence_count: number
}
interface Comparison {
  baseline: DrillRecord
  candidate: DrillRecord
  delta: { score: number; elapsed_seconds: number; evacuated: number | null; smoke_exposed: number | null; missing: number | null; congested: number | null; tasks_completed: number }
  verdict: string
  improvements: string[]
  regressions: string[]
  disclaimer: string
}
interface ComparisonResponse { runs: DrillRecord[]; comparison: Comparison | null }

const props = defineProps<{ apiBaseUrl: string; accessToken: string; sceneId: string; sceneName: string }>()
const emit = defineEmits<{ close: []; openDrill: [drillId: string] }>()
const api = createApiClient(props.apiBaseUrl, () => props.accessToken)
const runs = ref<DrillRecord[]>([])
const baselineId = ref('')
const candidateId = ref('')
const comparison = ref<Comparison | null>(null)
const loading = ref(false)
const comparing = ref(false)
const error = ref('')
let requestGeneration = 0

const baseline = computed(() => runs.value.find(run => run.id === baselineId.value) ?? null)
const candidate = computed(() => runs.value.find(run => run.id === candidateId.value) ?? null)
const canCompare = computed(() => Boolean(baselineId.value && candidateId.value && baselineId.value !== candidateId.value))
const metrics = computed(() => comparison.value ? [
  { key: 'score', label: '综合评分', baseline: comparison.value.baseline.score, candidate: comparison.value.candidate.score, delta: comparison.value.delta.score, unit: '分', positive: 'higher' },
  { key: 'elapsed_seconds', label: '处置用时', baseline: comparison.value.baseline.elapsed_seconds, candidate: comparison.value.candidate.elapsed_seconds, delta: comparison.value.delta.elapsed_seconds, unit: '秒', positive: 'lower' },
  { key: 'evacuated', label: '到达集合点', baseline: comparison.value.baseline.summary.evacuated, candidate: comparison.value.candidate.summary.evacuated, delta: comparison.value.delta.evacuated, unit: '人', positive: 'higher' },
  { key: 'smoke_exposed', label: '烟气暴露', baseline: comparison.value.baseline.summary.smoke_exposed, candidate: comparison.value.candidate.summary.smoke_exposed, delta: comparison.value.delta.smoke_exposed, unit: '人', positive: 'lower' },
  { key: 'missing', label: '失联人员', baseline: comparison.value.baseline.summary.missing, candidate: comparison.value.candidate.summary.missing, delta: comparison.value.delta.missing, unit: '人', positive: 'lower' },
  { key: 'congested', label: '拥堵人员', baseline: comparison.value.baseline.summary.congested, candidate: comparison.value.candidate.summary.congested, delta: comparison.value.delta.congested, unit: '人', positive: 'lower' },
  { key: 'tasks_completed', label: '完成任务', baseline: comparison.value.baseline.tasks.completed, candidate: comparison.value.candidate.tasks.completed, delta: comparison.value.delta.tasks_completed, unit: '项', positive: 'higher' },
] .filter(metric => metric.baseline !== null && metric.candidate !== null && metric.delta !== null) as Array<{ key: string; label: string; baseline: number; candidate: number; delta: number; unit: string; positive: string }> : [])

function formatDate(value: string | null): string {
  if (!value) return '结束时间未记录'
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}
function deltaText(delta: number, unit: string): string { return `${delta > 0 ? '+' : ''}${delta}${unit}` }
function deltaTone(metric: { delta: number; positive: string }): string {
  if (!metric.delta) return 'neutral'
  return (metric.delta > 0) === (metric.positive === 'higher') ? 'better' : 'worse'
}
function swapRuns(): void {
  const previous = baselineId.value
  baselineId.value = candidateId.value
  candidateId.value = previous
}
async function loadRuns(): Promise<void> {
  const generation = ++requestGeneration
  loading.value = true; error.value = ''; comparison.value = null
  try {
    const payload = await api.get<ComparisonResponse>(`/scenes/${encodeURIComponent(props.sceneId)}/outcome-comparison`)
    if (generation !== requestGeneration) return
    runs.value = payload.runs
    candidateId.value = payload.runs[0]?.id ?? ''
    baselineId.value = payload.runs[1]?.id ?? ''
    loading.value = false
    if (canCompare.value) await loadComparison()
  } catch (cause) {
    if (generation === requestGeneration) error.value = cause instanceof Error ? cause.message : '训练记录读取失败。'
  } finally { if (generation === requestGeneration) loading.value = false }
}
async function loadComparison(): Promise<void> {
  if (!canCompare.value) { comparison.value = null; return }
  const generation = ++requestGeneration
  comparing.value = true; error.value = ''
  try {
    const query = new URLSearchParams({ baseline_id: baselineId.value, candidate_id: candidateId.value })
    const payload = await api.get<ComparisonResponse>(`/scenes/${encodeURIComponent(props.sceneId)}/outcome-comparison?${query}`)
    if (generation === requestGeneration) { runs.value = payload.runs; comparison.value = payload.comparison }
  } catch (cause) {
    if (generation === requestGeneration) { comparison.value = null; error.value = cause instanceof Error ? cause.message : '训练对比失败。' }
  } finally { if (generation === requestGeneration) comparing.value = false }
}

watch(() => props.sceneId, () => void loadRuns(), { immediate: true })
</script>

<template>
  <section class="comparison-sheet" aria-labelledby="comparison-title">
    <header class="comparison-heading">
      <div><h2 id="comparison-title">训练成效对比</h2><p>{{ sceneName }} · 只比较已经结束并生成评分证据的训练。</p></div>
      <button class="comparison-close" type="button" aria-label="关闭训练对比" @click="emit('close')"><AppIcon name="close" :size="18" /></button>
    </header>

    <p v-if="error" class="comparison-message" role="alert">{{ error }} <button type="button" @click="loadRuns">重新读取</button></p>
    <div v-if="loading" class="comparison-state" aria-live="polite"><span></span><p>正在读取训练证据…</p></div>
    <div v-else-if="runs.length < 2" class="comparison-empty">
      <AppIcon name="compare" :size="28" /><div><h3>需要两次已结束训练</h3><p>完成一次基线训练，再调整路线或调度策略完成复演，这里会自动生成同口径对比。</p></div>
    </div>
    <template v-else>
      <form class="comparison-picker" @submit.prevent="loadComparison">
        <label><span>基线训练</span><select v-model="baselineId"><option v-for="run in runs" :key="run.id" :value="run.id" :disabled="run.id === candidateId">{{ run.name }} · {{ formatDate(run.ended_at) }}</option></select><small v-if="baseline">{{ baseline.evidence_count }} 条事件证据 · {{ baseline.score }} 分</small></label>
        <button class="swap-button" type="button" aria-label="交换基线与复演训练" @click="swapRuns"><AppIcon name="swap" :size="19" /></button>
        <label><span>复演训练</span><select v-model="candidateId"><option v-for="run in runs" :key="run.id" :value="run.id" :disabled="run.id === baselineId">{{ run.name }} · {{ formatDate(run.ended_at) }}</option></select><small v-if="candidate">{{ candidate.evidence_count }} 条事件证据 · {{ candidate.score }} 分</small></label>
        <UiButton type="submit" variant="primary" :loading="comparing" :disabled="!canCompare">生成对比</UiButton>
      </form>

      <div v-if="comparison" class="comparison-result" aria-live="polite">
        <div class="comparison-verdict"><AppIcon :name="comparison.regressions.length ? 'inspect' : 'check'" :size="22" /><div><strong>{{ comparison.verdict }}</strong><p>比较同一场景下的最终人员、任务、用时和评分记录。</p></div></div>
        <div class="comparison-table-wrap">
          <table>
            <thead><tr><th scope="col">指标</th><th scope="col">基线</th><th scope="col">复演</th><th scope="col">变化</th></tr></thead>
            <tbody><tr v-for="metric in metrics" :key="metric.key"><th scope="row">{{ metric.label }}</th><td>{{ metric.baseline }}{{ metric.unit }}</td><td>{{ metric.candidate }}{{ metric.unit }}</td><td><span class="delta" :data-tone="deltaTone(metric)">{{ deltaText(metric.delta, metric.unit) }}</span></td></tr></tbody>
          </table>
        </div>
        <div class="comparison-findings">
          <section><h3>形成改善</h3><ul v-if="comparison.improvements.length"><li v-for="item in comparison.improvements" :key="item"><AppIcon name="check" :size="15" />{{ item }}</li></ul><p v-else>本次没有形成可确认的改善指标。</p></section>
          <section><h3>需要复盘</h3><ul v-if="comparison.regressions.length"><li v-for="item in comparison.regressions" :key="item"><AppIcon name="inspect" :size="15" />{{ item }}</li></ul><p v-else>未发现数值退步；仍建议抽查关键操作证据。</p></section>
        </div>
        <div class="comparison-actions"><p>{{ comparison.disclaimer }}</p><div><UiButton variant="ghost" @click="emit('openDrill', comparison.baseline.id)">打开基线回放</UiButton><UiButton variant="secondary" @click="emit('openDrill', comparison.candidate.id)"><AppIcon name="play" :size="16" />打开复演回放</UiButton></div></div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.comparison-sheet{margin-top:2rem;border-top:1px solid var(--border-default,#aeb8b5);background:var(--surface-panel,#faf9f4);color:var(--text-primary,#1e2928)}
.comparison-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:1.5rem;padding:1.25rem 0 1rem}.comparison-heading h2{margin:0;font-size:1.35rem;letter-spacing:-.015em}.comparison-heading p{margin:.4rem 0 0;color:var(--text-secondary,#65736f);font-size:.78rem}.comparison-close,.swap-button{display:grid;place-items:center;min-width:44px;min-height:44px;border:1px solid var(--border-default,#aeb8b5);border-radius:8px;background:transparent;color:inherit}.comparison-close:hover,.swap-button:hover{background:var(--surface-subtle,#e8ece5)}
.comparison-message{margin:0 0 1rem;border:1px solid #d6a18f;border-radius:8px;background:#fbede7;color:#7f2f1d;padding:.75rem}.comparison-message button{border:0;background:transparent;color:inherit;font-weight:700;text-decoration:underline;text-underline-offset:3px}.comparison-state,.comparison-empty{display:flex;align-items:center;gap:1rem;min-height:9rem;border-top:1px solid #d3dad6;border-bottom:1px solid #d3dad6;color:#53635f}.comparison-state span{width:1rem;height:1rem;border:2px solid #aeb8b5;border-top-color:#173f3e;border-radius:50%;animation:spin .8s linear infinite}.comparison-empty h3,.comparison-empty p{margin:0}.comparison-empty p{max-width:58ch;margin-top:.4rem;color:#71807d;font-size:.78rem;line-height:1.6}
.comparison-picker{display:grid;grid-template-columns:minmax(0,1fr) 44px minmax(0,1fr) auto;align-items:end;gap:.8rem;border-top:1px solid #d3dad6;border-bottom:1px solid #d3dad6;padding:1rem 0}.comparison-picker label{display:grid;gap:.35rem;min-width:0}.comparison-picker label>span{font-size:.72rem;font-weight:750}.comparison-picker select{width:100%;min-height:44px;border:1px solid #aeb8b5;border-radius:8px;background:#fff;color:#1e2928;padding:0 .7rem}.comparison-picker small{color:#71807d;font-size:.68rem}.swap-button{align-self:center;margin-top:.2rem}.comparison-picker :deep(.ui-button){min-width:7.5rem;margin-bottom:1.1rem}
.comparison-result{padding-top:1rem}.comparison-verdict{display:flex;align-items:flex-start;gap:.8rem;background:#e8ece5;padding:1rem}.comparison-verdict strong{display:block;font-size:.9rem}.comparison-verdict p{margin:.3rem 0 0;color:#65736f;font-size:.72rem}.comparison-table-wrap{overflow-x:auto;border-bottom:1px solid #d3dad6}.comparison-table-wrap table{width:100%;min-width:34rem;border-collapse:collapse;font-variant-numeric:tabular-nums}.comparison-table-wrap th,.comparison-table-wrap td{border-bottom:1px solid #dfe4e1;padding:.72rem;text-align:right;font-size:.76rem}.comparison-table-wrap th:first-child{text-align:left}.comparison-table-wrap thead th{color:#71807d;font-size:.67rem;font-weight:650}.comparison-table-wrap tbody th{color:#34423f;font-weight:650}.delta{display:inline-flex;min-width:3.8rem;justify-content:center;border-radius:999px;padding:.18rem .45rem;font-weight:750}.delta[data-tone="better"]{background:#e1f1e8;color:#14543f}.delta[data-tone="worse"]{background:#f8e5df;color:#8a351f}.delta[data-tone="neutral"]{background:#eceeea;color:#687570}
.comparison-findings{display:grid;grid-template-columns:1fr 1fr;gap:2rem;padding:1.1rem 0}.comparison-findings section+section{border-left:1px solid #d3dad6;padding-left:2rem}.comparison-findings h3{margin:0;font-size:.82rem}.comparison-findings ul{display:grid;gap:.45rem;margin:.7rem 0 0;padding:0;list-style:none}.comparison-findings li{display:flex;align-items:center;gap:.45rem;color:#465652;font-size:.74rem}.comparison-findings p{margin:.7rem 0 0;color:#71807d;font-size:.74rem}.comparison-actions{display:flex;align-items:center;justify-content:space-between;gap:1.5rem;border-top:1px solid #d3dad6;padding:1rem 0}.comparison-actions>p{max-width:62ch;margin:0;color:#71807d;font-size:.68rem;line-height:1.55}.comparison-actions>div{display:flex;gap:.6rem;flex:0 0 auto}.comparison-actions :deep(.ui-button){gap:.4rem}
@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:860px){.comparison-picker{grid-template-columns:1fr 44px 1fr}.comparison-picker :deep(.ui-button){grid-column:1/-1;width:100%;margin:0}.comparison-actions{align-items:flex-start;flex-direction:column}.comparison-actions>div{width:100%;flex-wrap:wrap}}
@media(max-width:620px){.comparison-picker{grid-template-columns:1fr}.swap-button{justify-self:center;transform:rotate(90deg)}.comparison-findings{grid-template-columns:1fr;gap:1rem}.comparison-findings section+section{border-top:1px solid #d3dad6;border-left:0;padding-top:1rem;padding-left:0}.comparison-actions>div{display:grid;width:100%}.comparison-heading p{max-width:34ch}.comparison-picker select{font-size:1rem}}
@media(prefers-reduced-motion:reduce){.comparison-state span{animation:none}}
</style>
