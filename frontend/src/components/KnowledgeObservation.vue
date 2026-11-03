<script setup lang="ts">
import type { KnowledgeObservation } from '../domain/knowledge'
defineProps<{source:KnowledgeObservation;compact?:boolean}>()
const emit=defineEmits<{replay:[source:KnowledgeObservation]}>()
const clock=(seconds:number)=>`${Math.floor(seconds/60).toString().padStart(2,'0')}:${Math.floor(seconds%60).toString().padStart(2,'0')}`
const metrics=[{key:'arrived',label:'到集合点',unit:'人'},{key:'exposed',label:'暴露超阈值',unit:'人'},{key:'queue_seconds',label:'累计排队',unit:'人秒'}]as const
const parameterLabels:Record<string,string>={fire_source_type:'火源类型',fire_source_object_id:'起火对象',fire_floor:'起火楼层',fire_room:'起火房间',resident_count:'场景居民人数',stair_width:'楼梯净宽（米）',south_lane_status:'南侧通道',room_door_state:'起火房门'}
const parameterValues:Record<string,string>={kitchen:'住宅厨房',charging_shed:'充电棚',open:'开启',closed:'关闭',restricted:'受限',blocked:'封锁',available:'可用'}
</script>
<template>
  <section class="knowledge-observation" aria-label="经验原始观察依据">
    <h3>原始仿真观察</h3><p>{{source.drill_name||'来源演练'}} · 批准版本 {{source.revision}} · 观察 {{clock(source.observed_at)}} · {{source.population}} 人</p>
    <template v-if="!compact">
      <table><caption>冻结观察事实，与下方可修订正文分别保存</caption><thead><tr><th scope="col">指标</th><th scope="col">预测</th><th scope="col">观察</th></tr></thead><tbody><tr v-for="metric in metrics" :key="metric.key"><th scope="row">{{metric.label}}<small>{{metric.unit}}</small></th><td>{{source.predicted[metric.key]}}</td><td>{{source.actual[metric.key]}}</td></tr></tbody></table>
      <p>观察期间记录 {{source.intervention_count}} 条场次变化。发布前，请核对适用条件并补充复盘结论。</p>
      <details><summary>核对适用条件与模型版本</summary>
        <dl><template v-for="(value,key) in source.parameters" :key="key"><dt>{{parameterLabels[key]||key}}</dt><dd>{{parameterValues[String(value)]||value}}</dd></template></dl>
        <p>冻结场景版本：{{source.scene_version_id||'历史记录未提供'}}。</p>
        <p>模型修订：预测 {{source.forecast_engine_revision??'历史未记录'}} / 观察 {{source.observed_engine_revision??'历史未记录'}}。</p>
      </details>
      <button v-if="source.community_id&&source.scene_id" type="button" @click="emit('replay',source)">打开来源场次的观察时刻</button>
      <details v-if="source.events?.length"><summary>核对事件依据 · {{source.events.length}} 条</summary><ol><li v-for="event in source.events" :key="event.id"><strong>事件 {{event.sequence}} · {{clock(event.at_seconds)}}</strong><p>{{event.message}}</p></li></ol></details>
    </template>
    <small>观察校验 {{source.basis_hash.slice(0,12)}}</small>
  </section>
</template>
<style scoped>
.knowledge-observation{min-width:0;font-size:16px;line-height:1.7;padding-block:16px;margin-block:16px;border-block:1px solid currentColor;}
.knowledge-observation h3{font-size:18px;margin:0 0 8px;}.knowledge-observation p{overflow-wrap:anywhere;margin:8px 0;}
.knowledge-observation table{width:100%;border-collapse:collapse;table-layout:fixed;font-variant-numeric:tabular-nums;}.knowledge-observation caption{text-align:left;padding-block:8px;font-size:14px;}
.knowledge-observation th,.knowledge-observation td{text-align:right;padding:10px 6px;border-bottom:1px solid currentColor;overflow-wrap:anywhere;}.knowledge-observation th:first-child{width:44%;text-align:left;}
.knowledge-observation small{display:block;font-size:14px;font-weight:400;line-height:1.7;overflow-wrap:anywhere;}
.knowledge-observation button{min-height:44px;white-space:normal;}.knowledge-observation summary{min-height:44px;cursor:pointer;padding-block:8px;box-sizing:border-box;}
.knowledge-observation ol{list-style:none;padding:0;}.knowledge-observation li{padding-block:10px;border-bottom:1px solid currentColor;}
.knowledge-observation dl{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:8px 16px;margin:8px 0;}.knowledge-observation dt,.knowledge-observation dd{margin:0;overflow-wrap:anywhere;}
</style>
