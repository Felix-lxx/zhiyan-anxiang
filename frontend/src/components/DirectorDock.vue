<script setup lang="ts">
import UiIconButton from './ui/UiIconButton.vue'

const props = defineProps<{
  active: string
  taskCount: number
  eventCount: number
  score: number
}>()

const emit = defineEmits<{ open: [value: 'missions' | 'events' | 'assistant' | 'report' | 'more'] }>()
</script>

<template>
  <nav class="director-rail" aria-label="导演功能">
    <UiIconButton label="打开处置任务" icon="tasks" data-tooltip="处置任务" :data-active="props.active === 'missions'" @click="emit('open', 'missions')"><span>任务</span><b v-if="props.taskCount">{{ props.taskCount }}</b></UiIconButton>
    <UiIconButton label="打开事件证据" icon="pulse" data-tooltip="事件证据" :data-active="props.active === 'events'" @click="emit('open', 'events')"><span>事件</span><b v-if="props.eventCount">{{ props.eventCount }}</b></UiIconButton>
    <UiIconButton label="打开安巷 AI 教练" icon="brain" data-director-action="assistant" data-tooltip="AI 场景教练" :data-active="props.active === 'assistant'" @click="emit('open', 'assistant')"><span>AI 教练</span></UiIconButton>
    <UiIconButton label="打开复盘评分" icon="award" data-tooltip="复盘评分" :data-active="props.active === 'report'" @click="emit('open', 'report')"><span>复盘</span><em>{{ props.score }}</em></UiIconButton>
    <UiIconButton label="打开更多工具" icon="more" data-tooltip="更多工具" :data-active="['more','branches','participant','settings'].includes(props.active)" @click="emit('open', 'more')"><span>更多</span></UiIconButton>
  </nav>
</template>
