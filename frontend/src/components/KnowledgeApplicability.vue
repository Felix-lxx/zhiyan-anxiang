<script setup lang="ts">
import type {KnowledgeApplicability} from '../domain/knowledge'
defineProps<{value:KnowledgeApplicability}>()
const labels:Record<string,string>={kitchen:'住宅厨房',charging_shed:'充电棚',restricted:'受限',open:'开启',closed:'关闭',blocked:'封锁',available:'可用'}
const display=(value:string|number)=>labels[String(value)]??String(value)
</script>
<template>
  <section class="knowledge-applicability" aria-label="经验适用性核对">
    <strong>{{value.label}}</strong><p>{{value.notice}}</p>
    <ul v-if="value.differences.length"><li v-for="item in value.differences" :key="item.field">{{item.label}}：原观察 {{display(item.recorded)}}；本场 {{display(item.current)}}</li></ul>
    <p v-if="value.missing.length">来源缺项：{{value.missing.join('、')}}。</p>
    <small v-if="value.at_seconds!==undefined">核对起点 {{Math.floor(value.at_seconds/60).toString().padStart(2,'0')}}:{{Math.floor(value.at_seconds%60).toString().padStart(2,'0')}}，保留当时的判断。</small>
  </section>
</template>
<style scoped>
.knowledge-applicability{font-size:16px;line-height:1.7;min-width:0;margin-block:16px;padding-block:12px;border-bottom:1px solid currentColor;}
.knowledge-applicability p{margin:8px 0;}.knowledge-applicability ul{padding-inline-start:22px;margin-block:8px;}.knowledge-applicability li{margin-block:6px;overflow-wrap:anywhere;}
.knowledge-applicability small{display:block;font-size:14px;line-height:1.7;}strong{font-weight:600;}
</style>
