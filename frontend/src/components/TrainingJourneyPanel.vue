<script setup lang="ts">
import { computed } from 'vue'
import type { TrainingAction, TrainingJourney } from '../domain/training'
import AppIcon from './AppIcon.vue'

const props = defineProps<{ journey: TrainingJourney; status: string; busy: boolean }>()
const emit = defineEmits<{ action: [action: TrainingAction] }>()
const phases = [
  { id: 'prepare', label: '简报' }, { id: 'detect', label: '确认' },
  { id: 'respond', label: '执行' }, { id: 'verify', label: '核验' }, { id: 'review', label: '复盘' },
]
const isReady = computed(() => props.status === 'ready')
const isEnded = computed(() => props.status === 'ended')
function navigate(kind: TrainingAction['kind'], label: string, target_id: string | null = null) {
  emit('action', { id: kind, kind, label, target_id, detail: '', severity: 'normal' })
}
</script>

<template>
  <div class="training-journey">
    <ol class="training-journey__stages" aria-label="本次训练流程">
      <li v-for="phase in phases" :key="phase.id" :aria-current="journey.phase === phase.id ? 'step' : undefined">{{ phase.label }}</li>
    </ol>
    <section class="training-journey__current" aria-label="当前任务">
      <h3>{{ journey.title }}</h3>
      <p>{{ isReady ? journey.briefing.objective : journey.summary }}</p>
      <p v-if="journey.paused" class="training-journey__pause">时钟已暂停。可以查看对象和审阅方案；继续后人员移动与处置计时恢复。</p>
      <button v-if="journey.paused" :disabled="busy" type="button" @click="navigate('resume', '继续训练')"><AppIcon name="play" />继续训练</button>
      <ol class="training-journey__actions">
        <li v-for="action in journey.actions" :key="action.id">
          <button type="button" :disabled="busy" :data-urgent="action.severity === 'urgent'" @click="emit('action', action)">
            <span><strong>{{ action.label }}</strong><small>{{ action.detail }}</small></span><AppIcon name="arrowRight" :size="20" />
          </button>
        </li>
      </ol>
      <button v-if="journey.additional_action_count" class="training-journey__link" type="button" @click="navigate('missions', '全部处置任务')">还有 {{ journey.additional_action_count }} 项建议 · 查看全部处置任务</button>
    </section>
    <section v-if="journey.waiting.length" class="training-journey__waiting" aria-label="正在等待">
      <h3>正在等待</h3>
      <button v-for="item in journey.waiting" :key="item.id" type="button" @click="emit('action', item)"><AppIcon name="clock" /><span><strong>{{ item.label }}</strong><small>{{ item.detail }}{{ journey.paused ? ' · 暂停期间不推进' : '' }}</small></span></button>
    </section>
    <details class="training-journey__brief" :open="isReady">
      <summary>本次训练简报</summary>
      <p v-if="!isReady">{{ journey.briefing.objective }}</p>
      <dl class="training-journey__facts">
        <div><dt>案例与模式</dt><dd>{{ journey.briefing.case_title }} · {{ journey.briefing.mode === 'teaching' ? '教学' : '考核' }}</dd></div>
        <div><dt>起火位置</dt><dd>{{ journey.briefing.fire_location }}</dd></div>
        <div><dt>人员范围</dt><dd>{{ journey.briefing.population }} 人，含 {{ journey.briefing.priority_people.length }} 名重点人员</dd></div>
        <div><dt>护送岗位</dt><dd>{{ journey.resources.staff_available }}/{{ journey.resources.staff_total }} 个可用模拟岗位</dd></div>
        <div><dt>设备资源</dt><dd>{{ journey.resources.robot_state ? '1 台巡检广播机器人' : '无可用机器人' }} · {{ journey.resources.vehicles.length }} 辆应急车辆</dd></div>
      </dl>
      <p class="training-journey__meta">{{ journey.briefing_origin === 'frozen' ? '目标与初始配置已随场次冻结。设备和岗位状态随现场更新。' : '历史场次简报由原冻结配置生成，原始记录未改写。' }}</p>
      <h4>重点关注</h4>
      <ul v-if="journey.briefing.priority_people.length" class="training-journey__people"><li v-for="person in journey.briefing.priority_people" :key="person.id"><button type="button" @click="navigate('locate', person.label, person.id)">{{ person.label }}<span v-if="person.floor"> · {{ person.floor }} 层</span><AppIcon name="target" :size="16" /></button></li></ul>
      <p v-else>本场未配置重点人员。</p>
      <h4>责任任务</h4>
      <ul class="training-journey__responsibilities"><li v-for="task in journey.briefing.responsibilities" :key="task.id"><button type="button" @click="navigate('task', task.title, task.id)"><strong>{{ task.title }}</strong><small>{{ task.role }} · 接收、到位、提交证据</small></button></li></ul>
      <h4>结束前核对</h4>
      <ul><li v-for="condition in journey.briefing.completion_conditions" :key="condition">{{ condition }}</li></ul>
      <p>评价关注：{{ journey.briefing.measures.join('、') }}。</p>
    </details>
    <section v-if="!isReady" class="training-journey__completion" aria-label="完成条件">
      <h3>{{ isEnded ? '本场遗留事项' : '结束前仍需完成' }}</h3>
      <ul v-if="journey.completion.blockers.length"><li v-for="blocker in journey.completion.blockers" :key="blocker">{{ blocker }}</li></ul>
      <p v-else>人员、任务与执行状态已完成核对。</p>
      <div class="training-journey__links"><button type="button" @click="navigate('missions', '处置与执行')">处置与执行</button><button type="button" @click="navigate('rollcall', '集合清点')">集合清点</button></div>
    </section>
  </div>
</template>

<style scoped>
.training-journey { min-width:0; font-size:16px; line-height:1.65; color:var(--text-primary); }
.training-journey :is(p,ul,ol,dl) { margin:0; }
.training-journey :is(h3,h4) { font-size:18px; line-height:1.4; margin:0 0 12px; }
.training-journey h4 { margin-top:24px; font-size:16px; }
.training-journey button { min-height:44px; max-width:100%; font:inherit; overflow-wrap:anywhere; }
.training-journey__stages { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); padding:0 0 24px; list-style:none; gap:4px; }
.training-journey__stages li { text-align:center; padding:8px 0; font-size:14px; border-bottom:2px solid var(--border-default); color:var(--text-secondary); }
.training-journey__stages [aria-current] { color:var(--text-primary); border-color:var(--action-primary); font-weight:700; }
.training-journey__actions { list-style:none; padding:0; display:grid; gap:10px; margin-top:18px !important; }
.training-journey__actions button { display:flex; justify-content:space-between; align-items:center; gap:12px; width:100%; text-align:left; padding:14px; background:var(--surface-raised); border:1px solid var(--border-default); border-radius:8px; color:inherit; cursor:pointer; }
.training-journey__actions button[data-urgent=true] { border-color:var(--status-warning); }
.training-journey :is(strong,small) { display:block; }
.training-journey small,.training-journey__meta { font-size:14px; color:var(--text-secondary); }
.training-journey__actions svg { flex-shrink:0; }
.training-journey__pause { margin:14px 0 !important; }
.training-journey__current>button { margin-top:10px; }
.training-journey__waiting,.training-journey__brief,.training-journey__completion { border-top:1px solid var(--border-default); padding-top:22px; margin-top:24px; }
.training-journey__waiting button { width:100%; display:flex; align-items:center; text-align:left; gap:12px; padding:10px 0; border:0; background:none; color:inherit; cursor:pointer; }
.training-journey__brief summary { min-height:44px; cursor:pointer; font-weight:700; }
.training-journey__facts>div { padding:12px 0; border-bottom:1px solid var(--border-default); }
.training-journey__facts dt { font-size:14px; color:var(--text-secondary); }
.training-journey__facts dd { margin:3px 0 0; overflow-wrap:anywhere; }
.training-journey__meta { margin-top:12px !important; }
.training-journey__people { padding:0; list-style:none; display:flex; flex-wrap:wrap; gap:8px; }
.training-journey__people button { display:flex; align-items:center; gap:8px; }
.training-journey__responsibilities { padding:0; list-style:none; }
.training-journey__responsibilities button { width:100%; text-align:left; background:none; border:0; border-bottom:1px solid var(--border-default); color:inherit; padding:12px 0; cursor:pointer; }
.training-journey__completion ul,.training-journey__brief>ul:not([class]) { padding-left:22px; }
.training-journey__links { display:flex; gap:8px; flex-wrap:wrap; margin-top:18px; }
.training-journey button:focus-visible,.training-journey summary:focus-visible { outline:2px solid var(--text-primary); outline-offset:3px; }
</style>
