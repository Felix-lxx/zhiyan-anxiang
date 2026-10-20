<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { AgentOutcome } from '../domain/agent'
const props=defineProps<{ outcomes:AgentOutcome[];elapsed:number }>()
const emit=defineEmits<{ replay:[at:number] }>()
const revision=ref<number>()
watch(()=>props.outcomes[0]?.revision,value=>{revision.value=value},{immediate:true})
const item=computed(()=>props.outcomes.find(row=>row.revision===revision.value)??props.outcomes[0])
const metrics=[{key:'arrived',label:'到达集合点',unit:'人'},{key:'exposed',label:'暴露超阈值',unit:'人'},{key:'queue_seconds',label:'累计排队',unit:'人秒'}] as const
const clock=(value:number)=>`${Math.floor(value/60).toString().padStart(2,'0')}:${Math.floor(value%60).toString().padStart(2,'0')}`
const signed=(value:number)=>value>0?`+${value}`:`${value}`
</script>

<template>
  <section v-if="item" class="agent-outcome" aria-label="预测与实际结果核对">
    <header><h4>执行效果核对</h4><span>版本 {{item.revision}} · {{item.population}} 人</span></header>
    <label v-if="outcomes.length>1" class="agent-outcome__versions">查看批准版本
      <select v-model="revision"><option v-for="row in outcomes" :key="row.revision" :value="row.revision">版本 {{row.revision}} · {{row.title}}</option></select>
    </label>
    <p>{{item.title}} · 预演 {{clock(item.forecast_at)}} → {{clock(item.due_seconds)}}；{{clock(item.approved_at)}} 确认。</p>
    <p v-if="!item.result" role="status" class="agent-outcome__notice">{{elapsed>=item.due_seconds?'正在核对历史结果…':`等待演练推进到 ${clock(item.due_seconds)}，还需 ${Math.max(0,item.due_seconds-elapsed)} 秒演练时间。`}} 暂停期间不计时，关闭助手后仍由服务端核对。</p>
    <template v-else>
      <p class="agent-outcome__notice">{{item.result.notice}}</p>
      <table>
        <caption>观察时刻 {{clock(item.result.observed_at)}} · 实际核对 {{item.result.matched}} 人</caption>
        <thead><tr><th scope="col">指标</th><th scope="col">预测</th><th scope="col">实际</th><th scope="col">差值</th></tr></thead>
        <tbody><tr v-for="metric in metrics" :key="metric.key">
          <th scope="row">{{metric.label}}<small>{{metric.unit}}</small></th>
          <td>{{item.predicted[metric.key]}}</td><td>{{item.result.actual[metric.key]}}</td>
          <td>{{item.result.delta?signed(item.result.delta[metric.key]):'—'}}</td>
        </tr></tbody>
      </table>
      <p class="agent-outcome__meta">差值 = 实际 − 预测。暴露按累计烟气暴露值大于 5 统计；排队为本批居民累计等待时间之和。确认延迟 {{item.result.approval_delay_seconds}} 秒。</p>
      <details v-if="item.result.intervention_count">
        <summary>观察期间现场变化 · {{item.result.intervention_count}} 条</summary>
        <ol><li v-for="event in item.result.interventions" :key="event.id"><time>{{clock(event.at_seconds)}}</time><span>{{event.message}}<small>事件 {{event.sequence}}</small></span><button type="button" :aria-label="`回看事件 ${event.sequence}`" @click="emit('replay',event.at_seconds)">回看</button></li></ol>
        <p v-if="item.result.intervention_count>item.result.interventions.length" class="agent-outcome__meta">此处显示前 {{item.result.interventions.length}} 条；完整变化可在复盘事件列表查看。</p>
      </details>
      <p v-else class="agent-outcome__meta">观察期间未记录外部调度或环境变更。</p>
      <button type="button" class="agent-outcome__replay" @click="emit('replay',item.result.observed_at)">回看 {{clock(item.result.observed_at)}} 三维现场</button>
    </template>
  </section>
</template>

<style scoped>
.agent-outcome{min-width:0;margin-block:20px;padding-block:16px;border-block:1px solid #476653;color:#e9f1e8;font-size:16px;line-height:1.6}
header{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:8px}
h4{margin:0;font-size:18px}header span,.agent-outcome__meta{font-size:14px;color:#c1d3c4}
p{overflow-wrap:anywhere;margin:10px 0}.agent-outcome__notice{padding-inline-start:12px;border-inline-start:3px solid #b4ddb1}
table{width:100%;table-layout:fixed;border-collapse:collapse;font-size:16px;font-variant-numeric:tabular-nums}
caption{text-align:left;font-size:14px;color:#c1d3c4;padding-block:10px}
th,td{padding:10px 4px;border-bottom:1px solid #335347;text-align:right;overflow-wrap:anywhere}th:first-child{width:38%;text-align:left}thead th{font-size:14px;color:#c1d3c4;font-weight:500}
small{display:block;font-weight:400;font-size:14px;color:#c1d3c4}
summary{cursor:pointer;min-height:44px;align-content:center;overflow-wrap:anywhere}
ol{list-style:none;padding:0;margin:0}li{display:grid;grid-template-columns:48px minmax(0,1fr) auto;gap:8px;padding-block:12px;border-bottom:1px solid #335347}li span{min-width:0;overflow-wrap:anywhere}time{font-size:14px;font-variant-numeric:tabular-nums}
button{min-height:44px;white-space:normal}.agent-outcome__replay{width:100%;margin-top:12px}
.agent-outcome__versions{display:grid;gap:8px;margin-block:12px}.agent-outcome__versions select{width:100%;min-width:0;max-width:100%;font:inherit;min-height:44px;background:#0d241f;color:#edf5e7;border:1px solid #65836a;border-radius:6px;padding:8px}
@media(max-width:420px){th,td{padding-inline:2px}li{grid-template-columns:44px minmax(0,1fr)}li button{grid-column:2;justify-self:start}}
</style>
