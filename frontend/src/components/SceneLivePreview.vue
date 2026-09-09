<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from './AppIcon.vue'
import DigitalTwinArena from './DigitalTwinArena.vue'

const props = withDefaults(defineProps<{
  simulation: Record<string, unknown> | null
  loading?: boolean
  error?: string
  minute?: number
  draft?: boolean
  fireLevel?: string
  smokeLevel?: string
  riskLevel?: string
  compact?: boolean
}>(), { loading: false, error: '', minute: 0, draft: false, fireLevel: '—', smokeLevel: '—', riskLevel: '—', compact: false })

type ArenaSimulation = NonNullable<InstanceType<typeof DigitalTwinArena>['$props']['simulation']>
const arenaSimulation = computed(() => props.simulation as ArenaSimulation | null)
const structuralKey = computed(() => {
  const value = props.simulation as { world?: { fire_origin?: unknown; objects?: unknown[]; parameters?: unknown }; residents?: unknown[]; spatial_network?: { stair_width?: number }; road_network?: { edges?: Array<{ id?: string; status?: string }> }; environment?: { east_hydrant?: string } } | null
  return JSON.stringify([value?.world?.fire_origin, value?.world?.objects, value?.world?.parameters, value?.residents?.length, value?.spatial_network?.stair_width, value?.road_network?.edges?.map((edge) => [edge.id, edge.status]), value?.environment?.east_hydrant])
})
</script>

<template>
  <section class="scene-live-preview" :class="{ 'scene-live-preview--large': !compact }" aria-label="场景三维实时预览">
    <header>
      <div><AppIcon name="eye" /><span>三维现场预览</span></div>
      <span :data-draft="draft">{{ draft ? '未保存试算' : '已保存版本' }}</span>
    </header>
    <div class="scene-live-preview__viewport">
      <DigitalTwinArena v-if="arenaSimulation" :key="structuralKey" :simulation="arenaSimulation" :robot="null" status="running" :elapsed-seconds="minute * 60" compact :interactive="false" :effects-enabled="true" :camera-enabled="false" />
      <div v-else-if="loading" class="scene-live-preview__state"><AppIcon name="refresh" /><strong>正在计算三维现场</strong><span>读取社区版本、路网与人员配置…</span></div>
      <div v-else class="scene-live-preview__state" :data-error="Boolean(error)"><AppIcon :name="error ? 'pulse' : 'building'" /><strong>{{ error ? '暂时无法生成预览' : '等待场景参数' }}</strong><span>{{ error || '选择起火点后即可生成与正式演练一致的现场。' }}</span></div>
      <div v-if="loading && arenaSimulation" class="scene-live-preview__updating"><AppIcon name="refresh" />正在更新</div>
      <div v-if="error && arenaSimulation" class="scene-live-preview__error" role="alert"><strong>当前显示上一次成功预览</strong><span>{{ error }} 修改参数后将重新计算。</span></div>
    </div>
    <footer>
      <span><small>时刻</small><strong>{{ minute }} 分钟</strong></span>
      <span><small>火势</small><strong>{{ fireLevel }}</strong></span>
      <span><small>烟气</small><strong>{{ smokeLevel }}</strong></span>
      <span><small>风险</small><strong>{{ riskLevel }}</strong></span>
      <p>拖动旋转 · 滚轮缩放</p>
    </footer>
  </section>
</template>
