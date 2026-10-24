<script setup lang="ts">
import type { ExerciseTask } from '../domain/task'
import { computed, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import '../exercise.css'

interface TaskAssignee { id: string; name: string; online: boolean }
const props = defineProps<{ task: ExerciseTask; running: boolean; busy: boolean; readonly?: boolean; director?: boolean; assignees?: TaskAssignee[] }>()
const emit = defineEmits<{ action: [action: 'accept' | 'arrive' | 'submit', evidence: string]; assign: [participantId: string]; locate: []; dispatch: [] }>()
const evidence = ref('')
const label = computed(() => ({ waiting: '等待火情确认', pending: '待接收', executing: '前往目标', verifying: '处置与核验', completed: '已完成' }[props.task.status] ?? '历史任务'))
const urgency = computed(() => props.task.status === 'completed' ? 'done' : props.task.overdue ? 'overdue' : (props.task.remaining_seconds ?? Number.POSITIVE_INFINITY) <= 10 ? 'critical' : (props.task.remaining_seconds ?? Number.POSITIVE_INFINITY) <= 30 ? 'warning' : 'normal')
const visibleBlockers=computed(()=>(props.task.blockers??[]).filter(reason=>!(props.task.operation?.phase==='working'&&/^处置还需 \d+ 秒$/.test(reason))))
</script>

<template>
  <article class="task-workflow" :data-completed="task.status === 'completed'" :data-urgency="urgency">
    <p v-if="running && !task.verification_ready && ['warning','critical'].includes(urgency)" class="task-workflow__deadline" role="status"><AppIcon name="clock" />{{urgency==='critical'?'即将超时':'注意时限'}}：还剩 {{task.remaining_seconds}} 秒。先完成当前到位或处置步骤。</p>
    <p v-if="task.verification_ready && running && !readonly" class="task-workflow__verification" role="status">操作条件已满足，请提交核验证据。{{task.overdue?'已超时，仍可补救。':`剩余 ${task.remaining_seconds} 秒；动作完成不等于任务已核验。`}}</p>
    <header><span>{{ task.responsible_role ?? '历史处置任务' }}</span><strong :data-overdue="task.overdue">{{ task.status === 'completed' ? '已核验' : task.overdue ? '已超时 · 可补救' : `${task.remaining_seconds ?? task.deadline_seconds} 秒` }}</strong></header>
    <h3>{{ task.title }}</h3><p>{{ task.target }}</p>
    <div class="task-workflow__state"><AppIcon :name="task.status === 'completed' ? 'tasks' : 'target'" /><span>{{ label }}<template v-if="task.assignee"> · {{ task.assignee }}</template></span></div>
    <ol v-if="task.kind" class="task-workflow__steps" aria-label="任务处置步骤"><li :data-done="!['waiting','pending'].includes(task.status)">接收</li><li :data-done="['verifying','completed'].includes(task.status)">到位</li><li :data-done="task.status === 'completed'">核验</li></ol>
    <p v-if="task.evidence" class="task-workflow__evidence">结果证据：{{ task.evidence }}</p>
    <div v-if="task.operation && task.status==='verifying'" class="task-workflow__operation" aria-live="polite">
      <strong>{{task.operation.phase==='working'?`处置计时：还需 ${task.operation.remaining_seconds} 秒`:'处置计时结束，核对下方条件后提交证据'}}</strong>
      <progress :value="task.operation.elapsed_seconds" :max="Math.max(1,task.operation.duration_seconds)" aria-label="到位回执后的处置计时" />
      <p>计时以演练时钟为准；暂停时不推进。到位回执不代表虚拟人员已自动走到设备。</p>
    </div>
    <p v-if="task.completed_on_time===false" class="task-workflow__hint">核验晚于截止时间，已保留处置证据，但不计按时得分。</p>
    <p v-if="!running && task.status !== 'completed'">当前不可提交。{{ readonly ? '正在查看历史过程或其他角色任务。' : '请等待导演开始或继续演练。' }}</p>
    <template v-if="!readonly && running && task.kind && task.status !== 'completed'">
      <div v-if="director && ['waiting','pending'].includes(task.status) && !task.assignment_locked" class="task-workflow__assignment">
        <label :for="`assignee-${task.id}`">指定在线执行人
          <select :id="`assignee-${task.id}`" :value="task.assignee_id ?? ''" :disabled="busy || !(assignees?.length || task.assignee_id)" @change="($event.target as HTMLSelectElement).value && emit('assign', ($event.target as HTMLSelectElement).value)">
            <option value="">{{ assignees?.length ? '请选择在线成员' : '该角色暂无在线成员' }}</option>
            <option v-if="task.assignee_id && !assignees?.some(item => item.id === task.assignee_id)" :value="task.assignee_id">{{ task.assignee }} · 当前离线</option>
            <option v-for="member in assignees" :key="member.id" :value="member.id">{{ member.name }} · 在线</option>
          </select>
        </label>
        <p>{{ task.assignee_id ? `已预派给 ${task.assignee}，接收前仍可改派。` : '指派后仅该成员可接收；状态会实时同步到手机端。' }}</p>
      </div>
      <p v-if="director" class="task-workflow__hint">{{ task.assignee_id ? '手机端接收后锁定执行人，总控不能覆盖。' : '也可由总控代办，系统会记录实际操作者。' }}</p>
      <label v-if="task.status === 'verifying'" :for="`evidence-${task.id}`">处置结果（至少 6 字）<textarea :id="`evidence-${task.id}`" v-model="evidence" maxlength="500" placeholder="说明已完成的操作及核验结果" /></label>
      <ul v-if="task.status === 'verifying' && visibleBlockers.length" class="task-workflow__blockers"><li v-for="reason in visibleBlockers" :key="reason">{{ reason }}</li></ul>
      <div class="task-workflow__actions">
        <button v-if="task.status === 'pending' && (!director || !task.assignee_id)" type="button" :disabled="busy" @click="emit('action', 'accept', '')">{{ director ? '总控代办此任务' : '接收任务' }}</button>
        <button v-if="task.status === 'executing'" type="button" :disabled="busy" @click="emit('action', 'arrive', '')">回执已到达目标</button>
        <button v-if="task.status === 'verifying'" type="button" :disabled="busy || !task.can_submit || evidence.trim().length < 6" @click="emit('action', 'submit', evidence)">提交核验证据</button>
        <button v-if="director && task.target_position" type="button" @click="emit('locate')">定位目标</button>
        <button v-if="director && task.kind === 'broadcast'" type="button" :disabled="busy" @click="emit('dispatch')">派机器人到入口</button>
      </div>
    </template>
  </article>
</template>
<style scoped>
.task-workflow h3 { font-size:18px; line-height:1.5; }
.task-workflow>header>span { font-size:14px; }
.task-workflow__operation { display:grid; gap:8px; margin-block:16px; min-width:0; }
.task-workflow__operation strong { font-size:16px; overflow-wrap:anywhere; }
.task-workflow__operation progress { width:100%; height:8px; accent-color:var(--action-primary); }
.task-workflow__operation p { margin:0; font-size:14px; }
</style>
