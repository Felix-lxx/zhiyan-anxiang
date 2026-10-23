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
  fireSourceSelection?: { enabled: boolean; selectedId: string; eligibleIds: string[] }
  selectedSourceName?: string
  roomSelection?:boolean
}>(), { loading: false, error: '', minute: 0, draft: false, fireLevel: '—', smokeLevel: '—', riskLevel: '—', compact: false })
const emit = defineEmits<{ fireSourcePick: [objectId: string]; fireRoomPick:[value:{floor:number;room:string}] }>()

type ArenaSimulation = NonNullable<InstanceType<typeof DigitalTwinArena>['$props']['simulation']>
const arenaSimulation = computed(() => props.simulation as ArenaSimulation | null)
const structuralKey = computed(() => {
  const value = props.simulation as { world?: { fire_origin?: unknown; objects?: unknown[]; parameters?: unknown }; residents?: unknown[]; spatial_network?: { stair_width?: number }; road_network?: { edges?: Array<{ id?: string; status?: string }> }; environment?: { east_hydrant?: string } } | null
  // Fire, risk and routes update in place. Rebuilding them on each point pick
  // destroys the user's camera and reloads assets unnecessarily.
  const parameters=value?.world?.parameters as {start_time?:string;fire_source_type?:string;fire_floor?:number;fire_source_object_id?:string}|undefined
  return JSON.stringify([value?.world?.objects, parameters?.start_time, parameters?.fire_source_type==='kitchen'?[parameters.fire_source_object_id,parameters.fire_floor]:null, value?.residents?.length, value?.spatial_network?.stair_width])
})
</script>

<template>
  <section class="scene-live-preview" :class="{ 'scene-live-preview--large': !compact }" aria-label="场景三维实时预览">
    <header>
      <div><AppIcon name="eye" /><span>三维现场预览</span></div>
      <span :data-draft="draft">{{ draft ? '未保存试算' : '已保存版本' }}</span>
    </header>
    <div v-if="roomSelection" class="scene-live-preview__source-guide"><AppIcon name="building" :size="20"/><p><strong>厨房起火 · 楼内分区预览</strong><span>点击厨房台面或地面标记选房间；配置区切换楼栋、楼层和房门。烟气颜色随推演时刻更新。</span></p></div>
    <div v-if="fireSourceSelection" class="scene-live-preview__source-guide" role="status"><AppIcon name="fire" :size="20"/><p><strong>点选高亮充电棚设置火点</strong><span>当前选择：{{ selectedSourceName || '尚未选择' }}。金色为已选，浅绿为候选；保存后用于新场次。</span></p></div>
    <div class="scene-live-preview__viewport">
      <DigitalTwinArena v-if="arenaSimulation" :key="structuralKey" :simulation="arenaSimulation" :robot="null" status="running" :elapsed-seconds="minute * 60" compact :interactive="false" :effects-enabled="true" :camera-enabled="false" :fire-source-selection="fireSourceSelection" :room-selection="roomSelection" @fire-source-pick="id => emit('fireSourcePick', id)" @fire-room-pick="value=>emit('fireRoomPick',value)" />
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
