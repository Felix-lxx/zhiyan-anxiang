<script setup lang="ts">
import { computed } from 'vue'
import type { AgentRun } from '../domain/agent'
import AppIcon from './AppIcon.vue'
const props=defineProps<{run:AgentRun;candidateId?:string}>()
const emit=defineEmits<{focus:[id:string];robot:[];replay:[seconds:number]}>()
const context=computed(()=>props.run.revision_context)
const impact=computed(()=>props.run.impact?.changes_count?props.run.impact:props.run.status==='awaiting_approval'?context.value?.impact:undefined)
const recordedImpact=computed(()=>!props.run.impact?.changes_count&&!!context.value?.impact.changes_count)
const difference=computed(()=>context.value?.candidates.find(item=>item.candidate_id===props.candidateId))
const exitName=(exit:string)=>exit==='north'?'北侧出口':exit==='south'?'南侧出口':exit
const objectives:Record<string,string>={balanced:'风险与效率均衡',low_exposure:'优先降低暴露',fast_arrival:'优先尽快到场'}
</script>
<template>
  <section v-if="impact?.changes_count||context" class="revision-view" aria-label="异常影响与修订差异">
    <template v-if="impact?.changes_count">
      <h4>{{recordedImpact?'修订依据：已记录的现场变化':'本计划涉及的现场变化'}}</h4><p>原方案关联 {{impact.affected_count}} 名未到场居民、{{impact.step_count}} 个未完成步骤{{impact.robot_affected?'，同时涉及机器人行动':''}}。</p>
      <button v-if="impact.residents[0]" type="button" @click="emit('focus',impact.residents[0].id)"><AppIcon name="target" :size="18"/>定位受影响人员</button>
      <button v-else-if="impact.robot_affected" type="button" @click="emit('robot')">查看机器人</button>
      <details><summary>查看变化、人员与依赖</summary>
        <p v-if="impact.events_truncated" class="revision-view__meta">当前展示最近 100 条相关事件的影响，请结合完整事件时间线核对更早变化。</p>
        <ol><li v-for="change in impact.changes" :key="change.id"><strong>{{change.location||'现场事件'}} · 事件 {{change.sequence}}</strong><p>{{change.message}}</p><button type="button" @click="emit('replay',change.at_seconds)">定位这一历史时刻</button></li></ol>
        <ul><li v-for="person in impact.residents" :key="person.id"><strong>{{person.label}}</strong><p>{{person.location}} · {{person.reason}}</p><button type="button" @click="emit('focus',person.id)">三维定位</button></li></ul>
        <p v-for="step in impact.steps" :key="step.id">{{step.direct?'直接影响':'后续依赖'}}：{{step.label}}</p>
      </details>
    </template>
    <template v-if="context">
      <h4>本次修订改变了什么</h4><p>以{{context.baseline==='approved'?'原批准方案':'原首个候选'}}版本 {{context.from_revision}} 对照；{{difference?`${difference.changed_count} 名居民调整出口或剩余路线。`:'选择候选方案后查看人员变化。'}}</p>
      <p>本次取向：{{objectives[context.new_objective||run.scope.objective||'balanced']}}；禁用出口：{{(context.new_forbidden_exits||run.scope.forbidden_exits||[]).map(exitName).join('、')||'无'}}。</p>
      <p class="revision-view__meta">位置、暴露、队列和已受理命令保留。改道仅影响后续行动，新版本仍需确认。</p>
      <details v-if="difference?.residents.length"><summary>查看具体调整</summary><ul><li v-for="person in difference.residents" :key="person.resident_id"><strong>{{person.label}}</strong><p>{{person.exit_changed?`${exitName(person.old_exit)} → ${exitName(person.new_exit)}`:'出口不变，剩余通道已重新规划'}}</p><button type="button" @click="emit('focus',person.resident_id)">查看当前位置</button></li></ul></details>
    </template>
  </section>
</template>
<style scoped>
.revision-view{font-size:16px;line-height:1.7;padding-block:16px;border-block:1px solid var(--border-default);margin-block:16px;min-width:0;}
.revision-view h4{font-size:18px;margin:8px 0;}.revision-view p{margin:8px 0;overflow-wrap:anywhere;}.revision-view__meta{font-size:14px;color:var(--text-secondary);}
.revision-view summary{min-height:44px;padding-block:8px;cursor:pointer;box-sizing:border-box;}.revision-view ol,.revision-view ul{list-style:none;padding:0;}
.revision-view li{border-bottom:1px solid var(--border-default);padding-block:12px;}.revision-view button{display:inline-flex;align-items:center;gap:8px;min-height:44px;padding:8px 12px;font:inherit;border:1px solid var(--border-default);border-radius:8px;background:var(--surface-panel);color:var(--text-primary);cursor:pointer;}
</style>
