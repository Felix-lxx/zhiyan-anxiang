<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from './AppIcon.vue'
import type { TrainingAction, TrainingJourney } from '../domain/training'

const props=defineProps<{
  journey:TrainingJourney;status:string;arrived:number;counted:number;population:number;pendingTasks:number;busy:boolean
}>()
const emit=defineEmits<{overview:[];action:[value:TrainingAction];replay:[]}>()
const primary=computed<TrainingAction|undefined>(()=>props.status==='paused'
  ? {id:'resume',kind:'resume',label:'继续训练',detail:'恢复人员移动和处置计时',target_id:null,severity:'normal'}
  : props.journey.actions[0])
const phaseLabels={prepare:'训练简报',detect:'确认火情',respond:'组织处置',verify:'核验清点',review:'结果复盘'}
</script>
<template>
  <section class="director-progress" aria-label="当前训练进展">
    <button type="button" class="director-progress__overview" aria-label="查看当前任务详情" @click="emit('overview')">
      <span>{{phaseLabels[journey.phase]}} · {{status==='paused'?'时钟已暂停':status==='ended'?'结果已冻结':'当前阶段'}}</span>
      <strong>{{journey.title}}</strong>
      <small>到场 {{arrived}}/{{population}} 人 · 已清点 {{counted}} 人 · 待处置 {{pendingTasks}} 项</small>
    </button>
    <div class="director-progress__actions">
      <button v-if="primary" type="button" class="director-progress__primary" :disabled="busy" :title="primary.detail" @click="emit('action',primary)"><span>{{primary.label}}</span><AppIcon name="arrowRight" :size="18"/></button>
      <button v-if="status!=='ended'" type="button" class="director-progress__replay" :disabled="busy" aria-label="进入回放与复盘" @click="emit('replay')"><AppIcon name="history" :size="18"/><span>回放</span></button>
    </div>
  </section>
</template>
<style scoped>
.director-progress { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:16px; align-items:center; width:100%; min-width:0; }
.director-progress button { font:inherit; min-height:44px; border:1px solid #4a7162; border-radius:6px; color:#e9f3ed; cursor:pointer; }
.director-progress button.director-progress__overview { min-width:0; display:grid; gap:3px; padding:0; background:none; border:0; text-align:left; }
.director-progress__overview span,.director-progress__overview small { font-size:14px; line-height:1.5; color:#b9d6c9; }
.director-progress__overview strong { display:block; font-size:16px; line-height:1.5; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.director-progress__actions { display:flex; gap:8px; align-items:center; }
.director-progress__actions button { display:flex; align-items:center; justify-content:center; gap:8px; padding:10px 14px; }
.director-progress__actions .director-progress__primary { background:#c8e9d6; color:#123d2c; border-color:#c8e9d6; max-width:330px; }
.director-progress__primary span { overflow-wrap:anywhere; }
.director-progress__replay { background:#15382c; }
.director-progress button:focus-visible { outline:2px solid #b8e5cc; outline-offset:3px; }
.director-progress button:disabled { opacity:.55; cursor:default; }
@media(max-width:760px) {
 .director-progress { grid-template-columns:minmax(0,1fr); gap:8px; }
 .director-progress__overview { gap:1px; }
 .director-progress__overview strong { font-size:16px; }
 .director-progress__actions { width:100%; }
 .director-progress__actions .director-progress__primary { flex:1; max-width:none; }
 .director-progress__actions button { padding:8px 12px; font-size:14px; }
 .director-progress__overview small { font-size:14px; }
}
</style>
