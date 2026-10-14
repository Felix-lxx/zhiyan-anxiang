<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { createApiClient } from '../api/client'
import AppIcon from './AppIcon.vue'
import UiButton from './ui/UiButton.vue'

interface Readiness {
  version_name:string; checked_at:string; passed_count:number; total_count:number; notice:string
  checks:Array<{key:string;title:string;passed:boolean;detail:string;target:'map'|'scenes';action:string;query?:Record<string,string>}>
}
const props=defineProps<{ communityId:string; communityName?:string; apiBaseUrl:string; accessToken:string }>()
const api=createApiClient(props.apiBaseUrl,()=>props.accessToken), router=useRouter()
const result=ref<Readiness|null>(null), loading=ref(false), error=ref(''), showAll=ref(false)
let generation=0
const visibleChecks=computed(()=>result.value?.checks.filter(c=>showAll.value || !c.passed) ?? [])
async function load() {
  const request=++generation; loading.value=true; error.value=''
  try { const value=await api.get<Readiness>(`/communities/${props.communityId}/readiness`); if(request===generation)result.value=value }
  catch(cause) { if(request===generation)error.value=cause instanceof Error?cause.message:'准备检查读取失败，请重试。' }
  finally { if(request===generation)loading.value=false }
}
watch(()=>props.communityId,()=>{result.value=null;showAll.value=false;void load()},{immediate:true})
onBeforeUnmount(()=>generation++)
</script>

<template>
  <section class="community-readiness" aria-label="演练准备检查" :aria-busy="loading">
    <p v-if="communityName" class="readiness-community">{{communityName}}</p>
    <header><div><h2>演练准备检查</h2><p v-if="result">{{result.version_name}} · {{result.passed_count}} / {{result.total_count}} 项数据已具备<span v-if="!loading"> · {{new Date(result.checked_at).toLocaleTimeString('zh-CN',{hour12:false})}} 检查</span></p><p v-else>从社区基础数据到场景配置，定位需要补齐的内容。</p></div><UiButton :loading="loading" @click="load"><AppIcon name="refresh" :size="18"/>重新检查</UiButton></header>
    <p v-if="error" role="alert" class="readiness-error">{{error}} 请重试；当前结果可能已过时。</p>
    <p v-if="loading&&!result" role="status">正在检查楼栋、路网与场景…</p>
    <template v-if="result">
      <p v-if="!visibleChecks.length" class="readiness-complete"><AppIcon name="check"/>基础数据检查通过。仍需进入场景准备核对任务、参数与发布状态。</p>
      <ul><li v-for="item in visibleChecks" :key="item.key"><div><span :data-passed="item.passed">{{item.passed?'已具备':'待完善'}}</span><strong>{{item.title}}</strong></div><p>{{item.detail}}</p><UiButton variant="ghost" @click="router.push({name:item.target,params:{communityId},query:item.query})">{{item.action}}<AppIcon name="arrowRight" :size="18"/></UiButton></li></ul>
      <footer><button type="button" :aria-expanded="showAll" @click="showAll=!showAll">{{showAll?'只看待完善项':'查看全部检查项'}}</button><p>{{result.notice}}</p></footer>
    </template>
  </section>
</template>

<style scoped>
.community-readiness{min-width:0;margin-block:24px 32px;padding-block:24px;border-block:1px solid var(--border-default);font-size:var(--ui-body-size,16px);line-height:1.65}
.readiness-community{margin:0 0 8px;font-weight:600;overflow-wrap:anywhere}
.community-readiness header{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}.community-readiness h2{margin:0;font:700 24px/1.4 var(--atlas-display)}.community-readiness header p{margin:6px 0 0;color:var(--text-secondary);font-size:var(--ui-meta-size,14px)}
.community-readiness ul{list-style:none;padding:0;margin:20px 0 0}.community-readiness li{display:grid;grid-template-columns:minmax(180px,.7fr) minmax(0,1.5fr) auto;align-items:center;gap:20px;padding:16px 0;border-top:1px solid var(--border-default)}.community-readiness li>div{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.community-readiness li span{font-size:var(--ui-meta-size,14px);color:var(--status-warning)}.community-readiness li span[data-passed=true]{color:var(--status-success)}.community-readiness li p{margin:0;color:var(--text-secondary);overflow-wrap:anywhere}.community-readiness li button{white-space:nowrap}
.community-readiness footer{display:flex;align-items:baseline;gap:24px;flex-wrap:wrap;margin-top:16px}.community-readiness footer p{flex:1 1 320px;margin:0;font-size:var(--ui-meta-size,14px);color:var(--text-secondary)}.community-readiness footer button{min-height:44px;border:0;background:transparent;color:var(--text-primary);text-decoration:underline;text-underline-offset:4px;font-size:inherit;cursor:pointer}.readiness-error{color:var(--status-danger)}.readiness-complete{display:flex;align-items:flex-start;gap:10px;color:var(--status-success);margin:20px 0 0}.readiness-complete svg{flex:none;margin-top:3px}
@media(max-width:760px){.community-readiness li{grid-template-columns:minmax(0,1fr) auto;gap:8px 12px}.community-readiness li p{grid-column:1/-1;grid-row:2}.community-readiness li button{padding-inline:6px}.community-readiness h2{font-size:22px}}
</style>
