<script setup lang="ts">
import { computed, ref } from 'vue'
import type { CommandReceipt, Score } from '../domain/drill'
import AppIcon from './AppIcon.vue'

const props = defineProps<{ commands: CommandReceipt[]; score: Score; paused: boolean }>()
const emit = defineEmits<{ focus: [id: string]; evidence: [seconds: number]; ask: [command: CommandReceipt] }>()
const showAll = ref(false)
const filter = ref<'active' | 'all'>('active')
const activeStatuses = new Set<CommandReceipt['status']>(['submitted', 'accepted', 'executing', 'queued', 'blocked', 'paused'])
const labels: Record<CommandReceipt['status'], string> = { submitted: '正在提交', accepted: '已受理', completed: '已完成', executing: '执行中', queued: '排队等待', blocked: '执行受阻', paused: '已暂停', superseded: '已被新指令替代', cancelled: '已取消', unfinished: '结束时未完成', failed: '未执行' }
const activeCount = computed(() => props.commands.filter(command => activeStatuses.has(command.status)).length)
const blockedCount = computed(() => props.commands.filter(command => command.status === 'blocked').length)
const filtered = computed(() => {
  const commands = filter.value === 'active' ? props.commands.filter(command => activeStatuses.has(command.status)) : [...props.commands]
  return commands.sort((a, b) => Number(b.status === 'blocked') - Number(a.status === 'blocked') || b.accepted_at - a.accepted_at)
})
const visible = computed(() => showAll.value ? filtered.value : filtered.value.slice(0, 4))
const incomplete = computed(() => props.score.details.filter(d => d.max_score && d.score < d.max_score).slice(0, 2))
const time = (seconds: number) => `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
</script>

<template>
  <section class="execution-feedback" aria-label="指令执行进度">
    <header><h3>指令执行进度</h3><span>{{ paused ? '演练暂停' : '随现场同步' }}</span></header>
    <nav v-if="commands.length" class="execution-feedback__filters" aria-label="筛选演练指令">
      <button type="button" :aria-pressed="filter === 'active'" @click="filter = 'active'; showAll = false">运行中指令 {{ activeCount }}</button>
      <button type="button" :aria-pressed="filter === 'all'" @click="filter = 'all'; showAll = false">指令记录 {{ commands.length }}</button>
      <span v-if="blockedCount" role="status">{{ blockedCount }} 条受阻，优先处理</span>
    </nav>
    <p v-if="!commands.length" class="execution-feedback__empty">选择居民、道路或机器人并确认操作后，这里会显示实际执行进度、等待原因和结果证据。</p>
    <p v-else-if="!visible.length" class="execution-feedback__empty">当前没有待执行指令。切换“全部记录”查看执行结果与证据。</p>
    <ol>
      <li v-for="command in visible" :key="command.id" :data-status="command.status">
        <div class="execution-feedback__status"><time>{{ time(command.accepted_at) }}</time><strong>{{ labels[command.status] }}</strong><span v-if="command.remaining_seconds && command.remaining_seconds < 9999">行程估计 {{ Math.ceil(command.remaining_seconds) }} 秒</span><span v-if="command.score_before !== null && command.score_after_acceptance !== null && command.score_after_acceptance !== command.score_before">预计评分 {{ command.score_after_acceptance > command.score_before ? '+' : '' }}{{ command.score_after_acceptance - command.score_before }}</span></div>
        <h4>{{ command.label }}</h4><p>{{ command.reason }}</p>
        <p v-if="command.origin" class="execution-feedback__origin"><AppIcon :name="command.origin.kind==='agent'?'brain':'users'" :size="16"/><span>{{command.origin.kind==='agent'?`智能体计划 · 批准版本 ${command.origin.revision}`:'人工下令'}} · {{command.actor}}</span></p>
        <details class="execution-feedback__receipt"><summary>查看执行回执</summary><dl><div><dt>指令编号</dt><dd>{{command.id}}</dd></div><div><dt>受理时刻</dt><dd>{{time(command.accepted_at)}}</dd></div><div v-if="command.origin?.plan_id"><dt>关联计划</dt><dd>{{command.origin.plan_id}}</dd></div><div v-if="command.origin?.step_id"><dt>计划步骤</dt><dd>{{command.origin.step_id}}</dd></div><div v-if="command.failure_code"><dt>未执行原因码</dt><dd>{{command.failure_code}}</dd></div></dl></details>
        <progress v-if="command.kind === 'residents.assign' || command.kind === 'robot.command' || command.kind === 'search.assign'" :value="command.progress" max="1" :aria-label="command.label + '执行进度'"></progress>
        <div class="execution-feedback__actions"><span v-if="command.selected_count">到达 {{ command.completed_count }}/{{ command.selected_count }} 人</span><span v-else>{{ command.event_ids.length }} 条关联证据</span><button type="button" @click="emit('ask', command)"><AppIcon name="brain" :size="15" />分析原因</button><button v-if="command.resident_ids[0]" type="button" @click="emit('focus', command.resident_ids[0])"><AppIcon name="target" :size="15" />定位人员</button><button v-if="command.event_ids.length" type="button" @click="emit('evidence', command.accepted_at)">{{ command.status === 'failed' ? '查看失败记录' : '回看决定' }}<AppIcon name="arrowRight" :size="15" /></button></div>
      </li>
    </ol>
    <button v-if="filtered.length > 4" type="button" class="execution-feedback__more" :aria-expanded="showAll" @click="showAll = !showAll">{{ showAll ? '收起指令' : `展开其余 ${filtered.length - 4} 条指令` }}</button>
    <div class="execution-feedback__score"><h4>当前评分 {{ score.total_score }}/100</h4><p v-for="item in incomplete" :key="item.name"><strong>{{ item.name }} · {{ item.score }}/{{ item.max_score }}</strong><span>{{ item.evidence }}</span></p><small>人员到达、任务核验和清点后继续更新。行程估计不含后续排队与新扰动。</small></div>
  </section>
</template>

<style scoped>
.execution-feedback{color:var(--text-primary);min-width:0;margin-bottom:24px}
.execution-feedback>header{display:flex;align-items:center;justify-content:space-between;gap:12px;border-bottom:1px solid var(--border-default);padding-bottom:12px}
.execution-feedback h3,.execution-feedback h4{margin:0;font-size:var(--ui-body-size,16px);line-height:1.6}
.execution-feedback header>span,.execution-feedback small{font-size:var(--ui-meta-size,14px);color:var(--text-secondary)}
.execution-feedback__filters{display:flex;flex-wrap:wrap;gap:8px;margin-block:16px}
.execution-feedback__filters button{flex:1 1 120px}
.execution-feedback__filters button[aria-pressed=true]{background:var(--surface-raised);border-color:var(--action-focus);font-weight:600}
.execution-feedback__filters>span{flex-basis:100%;font-size:var(--ui-meta-size,14px);color:var(--status-warning)}
.execution-feedback ol{list-style:none;padding:0;margin:0}
.execution-feedback li{padding:16px 0;border-bottom:1px solid var(--border-default);overflow-wrap:anywhere}
.execution-feedback__status{display:flex;flex-wrap:wrap;align-items:center;gap:8px;font-size:var(--ui-meta-size,14px);margin-bottom:6px;font-variant-numeric:tabular-nums;color:var(--text-secondary)}
.execution-feedback__status time{flex-shrink:0;white-space:nowrap}
.execution-feedback__status strong{color:var(--text-primary)}
.execution-feedback .execution-feedback__origin{display:flex;align-items:flex-start;gap:8px;font-size:var(--ui-meta-size,14px);color:var(--text-secondary)}
.execution-feedback__origin svg{flex-shrink:0;margin-top:4px}
.execution-feedback__receipt{min-width:0;margin-block:8px;font-size:var(--ui-meta-size,14px);color:var(--text-secondary)}
.execution-feedback__receipt summary{min-height:44px;align-content:center;cursor:pointer;overflow-wrap:anywhere}
.execution-feedback__receipt dl{display:grid;gap:8px;margin:8px 0 16px}.execution-feedback__receipt dl>div{display:grid;grid-template-columns:90px minmax(0,1fr);gap:10px}
.execution-feedback__receipt dd{margin:0;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}
[data-status=blocked] .execution-feedback__status strong,[data-status=unfinished] .execution-feedback__status strong{color:var(--status-warning)}
[data-status=failed] .execution-feedback__status strong{color:var(--status-danger)}
[data-status=failed]{background:color-mix(in srgb,var(--status-danger) 8%,transparent)}
.execution-feedback p{font-size:var(--ui-body-size,16px);line-height:1.7;margin:7px 0;color:var(--text-secondary)}
.execution-feedback progress{display:block;width:100%;height:5px;margin:12px 0;accent-color:var(--status-success)}
.execution-feedback__actions{display:flex;flex-wrap:wrap;align-items:center;gap:8px;font-size:var(--ui-meta-size,14px);font-variant-numeric:tabular-nums}
.execution-feedback__actions>span{flex:1;color:var(--text-secondary)}
.execution-feedback button{display:inline-flex;align-items:center;justify-content:center;gap:5px;min-height:44px;padding:6px 9px;border:1px solid var(--border-default);border-radius:var(--radius-sm);background:transparent;color:var(--text-primary);font:inherit;font-size:var(--ui-label-size,16px);cursor:pointer}
.execution-feedback button:hover{background:var(--surface-raised)}
.execution-feedback button:focus-visible{outline:2px solid var(--action-focus);outline-offset:3px}
.execution-feedback__more{width:100%;margin-top:12px}
.execution-feedback__score{padding-top:20px}
.execution-feedback__score p>strong,.execution-feedback__score p>span{display:block}
.execution-feedback__score small{display:block;line-height:1.7}
@media(max-width:760px){.execution-feedback__actions button{flex:1}.execution-feedback__actions>span{flex-basis:100%}}
</style>
