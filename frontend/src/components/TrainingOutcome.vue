<script setup lang="ts">
import {computed} from 'vue'
import type {Drill} from '../domain/drill'
const props=defineProps<{drill:Drill}>()
const people=computed(()=>props.drill.simulation.residents)
const total=computed(()=>props.drill.simulation.summary.total)
const arrived=computed(()=>props.drill.simulation.summary.evacuated)
const counted=computed(()=>people.value.filter(person=>person.counted).length)
const verified=computed(()=>props.drill.tasks.filter(task=>task.status==='completed').length)
const intensity=computed(()=>props.drill.simulation.fire.intensity)
const activeFire=computed(()=>Number.isFinite(intensity.value)&&intensity.value>0)
const priorityRecommendation=computed(()=>props.drill.score?.recommendations?.[0]??'')
</script>
<template>
  <section class="training-outcome" aria-label="目标完成与剩余火情">
    <h3>训练结果与剩余风险</h3>
    <dl>
      <div><dt>居民到场与清点</dt><dd>{{arrived}} / {{total}} 人到场 · {{counted}} 人已清点</dd></div>
      <div><dt>责任任务核验</dt><dd>{{drill.tasks.length?`${verified} / ${drill.tasks.length} 项已核验`:'本场未配置处置任务'}}</dd></div>
      <div :data-fire-active="activeFire"><dt>{{drill.status==='ended'?'结束时火情':'当前火情'}}</dt><dd>{{Number.isFinite(intensity)?`火势指数 ${intensity}`:'火情数据未记录'}} · {{activeFire?'仍有火情':Number.isFinite(intensity)?'仿真火焰已熄灭':'待核对'}}</dd></div>
      <div v-if="priorityRecommendation" class="training-outcome__next"><dt>下一轮优先调整</dt><dd>{{priorityRecommendation}}</dd></div>
    </dl>
    <p>评分覆盖疏散、清点、责任任务、护送和响应；{{activeFire?'当前得分不表示灭火完成。':'火焰熄灭后仍需核对烟气与现场情况。'}}</p>
  </section>
</template>
<style scoped>
.training-outcome { margin-block:16px; padding-block:16px; border-block:1px solid #527564; min-width:0; }
.training-outcome h3 { margin:0 0 12px; font-size:18px; line-height:1.5; }
.training-outcome dl { display:grid; gap:12px; margin:0; }
.training-outcome dl>div { display:grid; gap:4px; }
.training-outcome dt { font-size:14px; color:var(--text-secondary,#b5c9be); }
.training-outcome dd { margin:0; font-size:16px; line-height:1.7; overflow-wrap:anywhere; }
.training-outcome [data-fire-active=true] dd { color:#ffca9e; }
.training-outcome__next { padding-top:12px; border-top:1px solid color-mix(in srgb,var(--text-secondary,#b5c9be) 34%,transparent); }
.training-outcome__next dd { max-width:72ch; }
.training-outcome p { margin:14px 0 0; font-size:14px; line-height:1.75; overflow-wrap:anywhere; }
</style>
