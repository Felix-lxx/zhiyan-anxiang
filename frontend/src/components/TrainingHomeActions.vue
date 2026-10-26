<script setup lang="ts">
import { ref, watch } from 'vue'
import { createApiClient } from '../api/client'
import type { TrainingJourney } from '../domain/training'
import type { DrillIndex } from '../domain/drill'
import AppIcon from './AppIcon.vue'

const props = defineProps<{
  apiBaseUrl: string; accessToken: string
  unfinished: DrillIndex | null; review: DrillIndex | null; loading: boolean; busy: boolean
}>()
const emit = defineEmits<{ resume: []; prepare: []; review: [] }>()
const api = createApiClient(props.apiBaseUrl, () => props.accessToken)
const journey = ref<TrainingJourney | null>(null)
const reading = ref(false), error = ref(''), retry = ref(0)
watch(() => [props.unfinished?.id, retry.value] as const, async ([id], _, onCleanup) => {
  journey.value = null; error.value = ''; reading.value = false
  if (!id) return
  const controller = new AbortController()
  let active = true
  onCleanup(() => { active = false; controller.abort() })
  reading.value = true
  try {
    const value = await api.get<TrainingJourney | null>(`/drills/${id}/journey`, { signal: controller.signal })
    if (active) journey.value = value
  } catch (cause) {
    if (active) error.value = cause instanceof Error ? cause.message : '进度暂时无法读取'
  } finally { if (active) reading.value = false }
}, { immediate: true })
</script>

<template>
  <section class="training-home" aria-label="训练工作安排">
    <div class="training-home__current">
      <h2>{{ unfinished ? '继续当前训练' : '准备一次训练' }}</h2>
      <template v-if="unfinished">
        <h3>{{ unfinished.name }}</h3>
        <p v-if="reading" role="status">正在读取上次停留的阶段…</p>
        <template v-else-if="journey"><strong>{{ journey.title }}</strong><p>{{ journey.summary }}</p><small>进度读取至 {{ Math.floor(journey.as_of_seconds / 60) }} 分 {{ journey.as_of_seconds % 60 }} 秒；进入后恢复实时同步。</small></template>
        <p v-else>{{ unfinished.status === 'ready' ? '配置已冻结，尚未启动。进入后核对本次训练简报。' : '恢复现场并查看未完成的处置、人员与指令。' }}</p>
        <p v-if="error" class="training-home__error" role="status">进度读取失败；仍可进入场次重新读取。<button type="button" @click="retry++">重试进度</button></p>
        <button class="training-home__primary" type="button" :disabled="busy || loading" @click="emit('resume')">{{ unfinished.status === 'ready' ? '核对简报并进入' : '恢复现场与当前任务' }}<AppIcon name="arrowRight" /></button>
      </template>
      <template v-else><p>{{ loading ? '正在读取训练记录…' : '选择案例、核对火点和人员。进入后先查看目标与结束条件，再开始演练。' }}</p><button class="training-home__primary" type="button" :disabled="busy || loading" @click="emit('prepare')">准备新训练<AppIcon name="arrowRight" /></button></template>
    </div>
    <div class="training-home__next">
      <button v-if="unfinished" class="training-home__secondary" type="button" :disabled="busy || loading" @click="emit('prepare')"><AppIcon name="tasks" /><span><strong>准备新训练</strong><small>配置火点、人员与责任任务</small></span><AppIcon name="arrowRight" /></button>
      <button class="training-home__secondary" type="button" :disabled="busy || loading || !review" @click="emit('review')"><AppIcon name="history" /><span><strong>{{ review ? '处理上次训练留下的问题' : '完成训练后查看改进线索' }}</strong><small>{{ review?.score?.recommendations[0] || (review ? '核对结果、失分证据与关键决定' : '复盘记录将保留决策和核验证据') }}</small></span><AppIcon name="arrowRight" /></button>
    </div>
  </section>
</template>

<style scoped>
.training-home { display:grid; grid-template-columns:minmax(0,1.45fr) minmax(0,1fr); gap:32px; margin:24px 0 32px; padding:26px 0; border-block:1px solid var(--border-default); }
.training-home__current { min-width:0; }
.training-home h2 { font-size:24px; margin:0 0 18px; line-height:1.35; }
.training-home h3 { font-size:18px; margin:0 0 12px; overflow-wrap:anywhere; }
.training-home p { font-size:16px; line-height:1.7; margin:8px 0 12px; }
.training-home small { display:block; color:var(--text-secondary); font-size:14px; line-height:1.6; }
.training-home button { font:inherit; min-height:44px; cursor:pointer; }
.training-home button:disabled { cursor:default; opacity:.6; }
.training-home button:focus-visible { outline:2px solid var(--action-primary); outline-offset:4px; }
.training-home__primary { display:inline-flex; align-items:center; gap:16px; margin-top:20px; padding:12px 18px; background:var(--action-primary); color:white; border:0; border-radius:8px; text-align:left; }
.training-home__next { align-self:center; min-width:0; }
.training-home__secondary { display:flex; width:100%; text-align:left; align-items:center; gap:14px; padding:20px 0; background:none; color:var(--text-primary); border:0; border-bottom:1px solid var(--border-default); }
.training-home__secondary span { flex:1; min-width:0; overflow-wrap:anywhere; }
.training-home__secondary strong { display:block; margin-bottom:6px; font-size:18px; }
.training-home svg { flex-shrink:0; }
.training-home__error { color:var(--status-danger); }
.training-home__error button { margin-left:8px; border:0; background:none; color:inherit; text-decoration:underline; }
@media(max-width:900px) { .training-home { grid-template-columns:1fr; gap:12px; } .training-home__primary { width:100%; justify-content:space-between; } }
</style>
