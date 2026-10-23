<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import UiButton from './ui/UiButton.vue'
import UiIconButton from './ui/UiIconButton.vue'
import UiStatus from './ui/UiStatus.vue'

const props = defineProps<{
  name: string
  subtitle: string
  socketState: 'connecting' | 'live' | 'stale'
  statusLabel: string
  displayClock: string
  drillStatus: string
  busy: boolean
  coachOpen: boolean
  replay: boolean
}>()

const emit = defineEmits<{
  back: []
  toggleCoach: []
  action: [value: 'start' | 'pause' | 'resume' | 'end']
  create: []
}>()
</script>

<template>
  <header class="director-topbar">
    <div class="director-brand">
      <UiIconButton label="返回项目" icon="back" @click="emit('back')" />
      <div><strong>三维导演台</strong><span :title="props.subtitle">{{ props.name }}</span></div>
    </div>
    <div class="director-status" aria-label="演练状态">
      <UiStatus class="sync-indicator" :tone="props.drillStatus === 'ended' || props.socketState === 'live' ? 'success' : 'warning'" live>{{ props.drillStatus === 'ended' ? '结果已冻结' : props.socketState === 'live' ? '实时同步' : '连接恢复中' }}</UiStatus>
      <span>{{ props.replay ? '历史回放' : props.statusLabel }}</span>
      <strong>{{ props.displayClock }}</strong>
    </div>
    <div class="director-actions">
      <UiButton class="director-actions__coach" variant="secondary" :aria-label="props.coachOpen ? '收起教练' : '训练教练'" :aria-pressed="props.coachOpen" @click="emit('toggleCoach')"><AppIcon name="compass" /><span>{{ props.coachOpen ? '收起教练' : '训练教练' }}</span></UiButton>
      <UiButton v-if="props.drillStatus === 'ready'" class="director-actions__primary" variant="primary" :disabled="props.busy" aria-label="开始推演" @click="emit('action', 'start')"><AppIcon name="play" /><span>开始推演</span></UiButton>
      <UiButton v-if="props.drillStatus === 'running'" :disabled="props.busy" aria-label="暂停演练" @click="emit('action', 'pause')"><AppIcon name="pause" /><span>暂停</span></UiButton>
      <UiButton v-if="props.drillStatus === 'paused'" :disabled="props.busy" aria-label="继续演练" @click="emit('action', 'resume')"><AppIcon name="play" /><span>继续</span></UiButton>
      <UiButton v-if="['running','paused'].includes(props.drillStatus)" class="director-actions__end" variant="danger" :disabled="props.busy" aria-label="结束并评分" @click="emit('action', 'end')"><AppIcon name="stop" /><span>结束评分</span></UiButton>
      <UiButton v-if="props.drillStatus === 'ended'" class="director-actions__primary" variant="primary" :disabled="props.busy" aria-label="创建新一轮演练" @click="emit('create')"><AppIcon name="refresh" /><span>新开一轮</span></UiButton>
    </div>
  </header>
</template>
