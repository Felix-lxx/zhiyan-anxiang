<script setup lang="ts">
import type { AgentPlanningReport } from '../domain/agent'
defineProps<{report:AgentPlanningReport}>()
</script>
<template>
  <section class="planning-evidence" aria-label="知识与工具规划记录">
    <h4>本次规划依据</h4>
    <p>{{report.objective_label}} · {{report.mode==='model_tools'?'模型已调用只读工具核对':'领域工具约束规划'}}</p>
    <p>{{report.explanation||report.notice}}</p>
    <p v-if="report.knowledge_assessment?.experience_count">{{report.knowledge_assessment.notice}}</p>
    <p v-if="report.citations?.length" class="planning-evidence__meta">参考 {{report.citations.map(id=>'['+id+']').join('、')}}，原文见本计划参考资料。</p>
    <details><summary>查看工具记录 · 事件 {{report.event_sequence}}</summary>
      <p v-if="report.ranking_method" class="planning-evidence__meta">{{report.ranking_method}}</p>
      <ol><li v-for="(item,index) in report.trace" :key="index"><strong>{{item.label}}</strong><span>{{item.status==='rejected'?'校验未通过，已要求修订':'已完成'}}{{item.round?` · 第 ${item.round} 轮`:''}}</span><p>{{item.summary}}</p></li></ol>
      <p class="planning-evidence__meta">工具读取的是本次预演起点，现场变化后需要重新比较。记录仅包含工具结果，不展示模型内部推理。</p>
      <ul v-if="report.checks.some(check=>!check.valid)"><li v-for="check in report.checks.filter(item=>!item.valid)" :key="check.candidate_id">{{check.candidate_id}}：{{check.blockers.join('；')||'未满足执行条件'}}</li></ul>
    </details>
  </section>
</template>
<style scoped>
.planning-evidence{padding-block:16px;margin-block:16px;border-block:1px solid var(--border-default);font-size:16px;line-height:1.7;min-width:0;}
.planning-evidence h4{margin:0 0 8px;font-size:18px;}.planning-evidence p{margin:6px 0;overflow-wrap:anywhere;}
.planning-evidence summary{cursor:pointer;min-height:44px;padding-block:8px;box-sizing:border-box;}
.planning-evidence ol{padding:0;list-style:none;}.planning-evidence li{padding-block:10px;border-bottom:1px solid var(--border-default);}
.planning-evidence li>strong,.planning-evidence li>span{display:block;}.planning-evidence__meta,.planning-evidence li>span{color:var(--text-secondary);font-size:14px;}
</style>
