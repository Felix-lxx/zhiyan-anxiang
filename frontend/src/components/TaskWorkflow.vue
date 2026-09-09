<script setup lang="ts">
import type { ExerciseTask } from '../domain/task'
import { computed, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import '../exercise.css'

const props = defineProps<{ task: ExerciseTask; running: boolean; busy: boolean; readonly?: boolean; director?: boolean }>()
const emit = defineEmits<{ action: [action: 'accept' | 'arrive' | 'submit', evidence: string]; locate: []; dispatch: [] }>()
const evidence = ref('')
const label = computed(() => ({ waiting: '等待火情确认', pending: '待接收', executing: '前往目标', verifying: '处置与核验', completed: '已完成' }[props.task.status] ?? '历史任务'))
</script>

<template>
  <article class="task-workflow" :data-completed="task.status === 'completed'">
    <header><span>{{ task.responsible_role ?? '历史处置任务' }}</span><strong :data-overdue="task.overdue">{{ task.status === 'completed' ? '已核验' : task.overdue ? '已超时 · 可补救' : `${task.remaining_seconds ?? task.deadline_seconds} 秒` }}</strong></header>
    <h3>{{ task.title }}</h3><p>{{ task.target }}</p>
    <div class="task-workflow__state"><AppIcon :name="task.status === 'completed' ? 'tasks' : 'target'" /><span>{{ label }}<template v-if="task.assignee"> · {{ task.assignee }}</template></span></div>
    <ol v-if="task.kind" class="task-workflow__steps" aria-label="任务处置步骤"><li :data-done="!['waiting','pending'].includes(task.status)">接收</li><li :data-done="['verifying','completed'].includes(task.status)">到位</li><li :data-done="task.status === 'completed'">核验</li></ol>
    <p v-if="task.evidence" class="task-workflow__evidence">结果证据：{{ task.evidence }}</p>
    <p v-if="!running && task.status !== 'completed'">当前不可提交。{{ readonly ? '正在查看历史过程或其他角色任务。' : '请等待导演开始或继续演练。' }}</p>
    <template v-if="!readonly && running && task.kind && task.status !== 'completed'">
      <p v-if="director" class="task-workflow__hint">总控代办会记录操作者；已被手机端接收的任务不可覆盖。</p>
      <label v-if="task.status === 'verifying'" :for="`evidence-${task.id}`">处置结果（至少 6 字）<textarea :id="`evidence-${task.id}`" v-model="evidence" maxlength="500" placeholder="说明已完成的操作及核验结果" /></label>
      <ul v-if="task.status === 'verifying' && task.blockers?.length" class="task-workflow__blockers"><li v-for="reason in task.blockers" :key="reason">{{ reason }}</li></ul>
      <div class="task-workflow__actions">
        <button v-if="task.status === 'pending'" type="button" :disabled="busy" @click="emit('action', 'accept', '')">接收任务</button>
        <button v-if="task.status === 'executing'" type="button" :disabled="busy" @click="emit('action', 'arrive', '')">回执已到达目标</button>
        <button v-if="task.status === 'verifying'" type="button" :disabled="busy || !task.can_submit || evidence.trim().length < 6" @click="emit('action', 'submit', evidence)">提交核验证据</button>
        <button v-if="director && task.target_position" type="button" @click="emit('locate')">定位目标</button>
        <button v-if="director && task.kind === 'broadcast'" type="button" :disabled="busy" @click="emit('dispatch')">派机器人到入口</button>
      </div>
    </template>
  </article>
</template>
