<script setup lang="ts">
import UiIconButton from './ui/UiIconButton.vue'

const props = defineProps<{
  active: string
  taskCount: number
  verificationCount?: number
  urgentCount?: number
  eventCount: number
  score: number
}>()

const emit = defineEmits<{ open: [value: 'missions' | 'events' | 'assistant' | 'report' | 'more'] }>()
</script>

<template>
  <nav class="director-rail" aria-label="导演功能">
    <UiIconButton label="打开处置任务" icon="tasks" :data-tooltip="props.verificationCount?'动作已满足，等待提交核验证据':props.urgentCount?'任务即将超时':'处置任务'" :data-active="props.active === 'missions'" @click="emit('open', 'missions')"><span>{{props.verificationCount?'待核验':props.urgentCount?'即将超时':'任务'}}</span><b v-if="props.taskCount">{{ props.verificationCount || props.urgentCount || props.taskCount }}</b></UiIconButton>
    <UiIconButton label="打开事件证据" icon="pulse" data-tooltip="事件证据" :data-active="props.active === 'events'" @click="emit('open', 'events')"><span>事件</span><b v-if="props.eventCount">{{ props.eventCount }}</b></UiIconButton>
    <UiIconButton label="打开安巷指挥助手" icon="brain" data-director-action="assistant" data-tooltip="目标计划与场景对话" :data-active="props.active === 'assistant'" @click="emit('open', 'assistant')"><span>指挥助手</span></UiIconButton>
    <UiIconButton label="打开复盘评分" icon="award" data-tooltip="复盘评分" :data-active="props.active === 'report'" @click="emit('open', 'report')"><span>复盘</span><em>{{ props.score }}</em></UiIconButton>
    <UiIconButton label="打开更多工具" icon="more" data-tooltip="更多工具" :data-active="['more','branches','participant','settings'].includes(props.active)" @click="emit('open', 'more')"><span>更多</span></UiIconButton>
  </nav>
</template>
