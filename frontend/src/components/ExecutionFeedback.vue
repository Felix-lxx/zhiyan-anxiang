<script setup lang="ts">
import { computed, ref } from 'vue'
import type { CommandReceipt, Score } from '../domain/drill'
import AppIcon from './AppIcon.vue'

const props = defineProps<{ commands: CommandReceipt[]; score: Score; paused: boolean }>()
const emit = defineEmits<{ focus: [id: string]; evidence: [seconds: number]; ask: [command: CommandReceipt] }>()
const showAll = ref(false)
const labels: Record<CommandReceipt['status'], string> = { submitted: '正在提交', accepted: '已受理', completed: '已完成', executing: '执行中', queued: '排队等待', blocked: '执行受阻', paused: '已暂停', superseded: '已被新指令替代', cancelled: '已取消', unfinished: '结束时未完成', failed: '未执行' }
const visible = computed(() => showAll.value ? props.commands : props.commands.slice(0, 4))
const incomplete = computed(() => props.score.details.filter(d => d.max_score && d.score < d.max_score).slice(0, 2))
const time = (seconds: number) => `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
</script>

<template>
  <section class="execution-feedback" aria-label="指令执行进度">
    <header><h3>指令执行进度</h3><span>{{ paused ? '演练暂停' : '随现场同步' }}</span></header>
    <p v-if="!commands.length" class="execution-feedback__empty">选择居民、道路或机器人并确认操作后，这里会显示实际执行进度、等待原因和结果证据。</p>
    <ol aria-live="polite">
      <li v-for="command in visible" :key="command.id" :data-status="command.status">
        <div class="execution-feedback__status"><time>{{ time(command.accepted_at) }}</time><strong>{{ labels[command.status] }}</strong><span v-if="command.remaining_seconds && command.remaining_seconds < 9999">行程估计 {{ Math.ceil(command.remaining_seconds) }} 秒</span><span v-if="command.score_before !== null && command.score_after_acceptance !== null && command.score_after_acceptance !== command.score_before">预计评分 {{ command.score_after_acceptance > command.score_before ? '+' : '' }}{{ command.score_after_acceptance - command.score_before }}</span></div>
        <h4>{{ command.label }}</h4><p>{{ command.reason }}</p>
        <progress v-if="command.kind === 'residents.assign' || command.kind === 'robot.command' || command.kind === 'search.assign'" :value="command.progress" max="1" :aria-label="command.label + '执行进度'"></progress>
        <div class="execution-feedback__actions"><span v-if="command.selected_count">到达 {{ command.completed_count }}/{{ command.selected_count }} 人</span><span v-else>{{ command.event_ids.length }} 条关联证据</span><button type="button" @click="emit('ask', command)"><AppIcon name="brain" :size="15" />分析原因</button><button v-if="command.resident_ids[0]" type="button" @click="emit('focus', command.resident_ids[0])"><AppIcon name="target" :size="15" />定位人员</button><button v-if="command.event_ids.length" type="button" @click="emit('evidence', command.accepted_at)">{{ command.status === 'failed' ? '查看失败记录' : '回看决定' }}<AppIcon name="arrowRight" :size="15" /></button></div>
      </li>
    </ol>
    <button v-if="commands.length > 4" type="button" class="execution-feedback__more" :aria-expanded="showAll" @click="showAll = !showAll">{{ showAll ? '收起历史指令' : `查看本场最近 ${commands.length} 条指令` }}</button>
    <div class="execution-feedback__score"><h4>当前评分 {{ score.total_score }}/100</h4><p v-for="item in incomplete" :key="item.name"><strong>{{ item.name }} · {{ item.score }}/{{ item.max_score }}</strong><span>{{ item.evidence }}</span></p><small>人员到达、任务核验和清点后继续更新。行程估计不含后续排队与新扰动。</small></div>
  </section>
</template>

<style scoped>
.execution-feedback{color:var(--text-primary);min-width:0;margin-bottom:24px}
.execution-feedback>header{display:flex;align-items:center;justify-content:space-between;gap:12px;border-bottom:1px solid var(--border-default);padding-bottom:12px}
.execution-feedback h3,.execution-feedback h4{margin:0;font-size:15px;line-height:1.6}
.execution-feedback header>span,.execution-feedback small{font-size:13px;color:var(--text-secondary)}
.execution-feedback ol{list-style:none;padding:0;margin:0}
.execution-feedback li{padding:16px 0;border-bottom:1px solid var(--border-default);overflow-wrap:anywhere}
.execution-feedback__status{display:flex;flex-wrap:wrap;align-items:center;gap:8px;font-size:13px;margin-bottom:6px;font-variant-numeric:tabular-nums;color:var(--text-secondary)}
.execution-feedback__status strong{color:var(--text-primary)}
[data-status=blocked] .execution-feedback__status strong,[data-status=unfinished] .execution-feedback__status strong{color:var(--status-warning)}
[data-status=failed] .execution-feedback__status strong{color:var(--status-danger)}
[data-status=failed]{background:color-mix(in srgb,var(--status-danger) 8%,transparent)}
.execution-feedback p{font-size:13px;line-height:1.7;margin:7px 0;color:var(--text-secondary)}
.execution-feedback progress{display:block;width:100%;height:5px;margin:12px 0;accent-color:var(--status-success)}
.execution-feedback__actions{display:flex;flex-wrap:wrap;align-items:center;gap:8px;font-size:13px;font-variant-numeric:tabular-nums}
.execution-feedback__actions>span{flex:1;color:var(--text-secondary)}
.execution-feedback button{display:inline-flex;align-items:center;justify-content:center;gap:5px;min-height:44px;padding:6px 9px;border:1px solid var(--border-default);border-radius:var(--radius-sm);background:transparent;color:var(--text-primary);font:inherit;font-size:13px;cursor:pointer}
.execution-feedback button:hover{background:var(--surface-raised)}
.execution-feedback button:focus-visible{outline:2px solid var(--action-focus);outline-offset:3px}
.execution-feedback__more{width:100%;margin-top:12px}
.execution-feedback__score{padding-top:20px}
.execution-feedback__score p>strong,.execution-feedback__score p>span{display:block}
.execution-feedback__score small{display:block;line-height:1.7}
@media(max-width:760px){.execution-feedback__actions button{flex:1}.execution-feedback__actions>span{flex-basis:100%}}
</style>
