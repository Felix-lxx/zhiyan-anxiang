<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { createApiClient } from '../api/client'
import type { TrainingArchive } from '../domain/training'

const props=defineProps<{apiBaseUrl:string;accessToken:string;drillId:string;status:string}>()
const emit=defineEmits<{knowledge:[documentId:string]}>()
const api=createApiClient(props.apiBaseUrl,()=>props.accessToken)
const archive=ref<TrainingArchive|null>(null),loading=ref(false),error=ref('')
let controller:AbortController|null=null
const experienceStatus=computed(()=>{
  const version=archive.value?.experience?.versions[0]
  return version?({draft:'待补充草稿',review:'待审核',published:'已发布',withdrawn:'已停用',expired:'已过期',failed:'提取失败'}[version.effective_status??version.status]??'待核对'):''
})
async function load(backfill=false){
  controller?.abort()
  if(props.status!=='ended'){archive.value=null;loading.value=false;return}
  const request=new AbortController();controller=request;loading.value=true;error.value=''
  const timeout=window.setTimeout(()=>request.abort(),15000)
  try{
    const path=`/drills/${props.drillId}/archive`
    const result=backfill?await api.post<{archive:TrainingArchive|null}>(path,undefined,{signal:request.signal}):await api.get<{archive:TrainingArchive|null}>(path,{signal:request.signal})
    if(controller===request)archive.value=result.archive
  }catch(cause){if(controller===request)error.value=cause instanceof Error&&cause.name!=='AbortError'?cause.message:'读取训练档案超时，请重试。'}
  finally{window.clearTimeout(timeout);if(controller===request)loading.value=false}
}
function download(){
  if(!archive.value)return
  const url=URL.createObjectURL(new Blob([JSON.stringify(archive.value,null,2)],{type:'application/json;charset=utf-8'}))
  const anchor=document.createElement('a');anchor.href=url;anchor.download=`training-archive-${archive.value.drill_id}.json`;anchor.click()
  window.setTimeout(()=>URL.revokeObjectURL(url),1000)
}
watch(()=>[props.drillId,props.status],()=>{archive.value=null;void load()},{immediate:true})
onBeforeUnmount(()=>{controller?.abort();controller=null})
</script>
<template>
  <section v-if="status==='ended'" class="training-archive" aria-label="训练档案与经验回收" :aria-busy="loading">
    <header><h3>训练档案</h3><span v-if="archive">已归档</span></header>
    <p v-if="loading" role="status">正在读取训练档案…</p>
    <div v-else-if="error" role="alert"><p>{{error}}</p><button type="button" @click="load()">重新读取档案</button></div>
    <template v-else-if="archive">
      <p>到场 {{archive.data.metrics.arrived}} / {{archive.data.metrics.population}} 人，已清点 {{archive.data.metrics.counted}} 人；责任任务已核验 {{archive.data.metrics.tasks_verified}} / {{archive.data.metrics.tasks_total}} 项。</p>
      <p>已关联 {{archive.data.event_count}} 条过程事件{{archive.experience?'；本场经验：'+experienceStatus:'；未保留经验草稿'}}。</p>
      <div class="training-archive__actions"><button v-if="archive.experience" type="button" @click="emit('knowledge',archive.experience.id)">{{experienceStatus==='已发布'?'查看本场经验':'完善与审核经验'}}</button><button type="button" @click="download">下载训练档案</button></div>
      <details><summary>查看本场发现与归档依据</summary><ul><li v-for="finding in archive.data.findings" :key="finding">{{finding}}</li></ul><p>结束时已保存 {{archive.data.conversation_count_at_end}} 轮助手问答；对话可在助手中继续查看或单独清空。</p><p v-if="archive.data.origin==='historical_reconstruction'">本档案由历史冻结配置与事件补建，保留原始成绩；原运行模型修订未确认。</p><p v-else>场景、结果与模型修订在结束训练时一起冻结。经验草稿需审核发布，才供后续检索。</p><small>归档时间 {{new Date(archive.created_at).toLocaleString('zh-CN')}}<br/>内容校验 {{archive.content_hash.slice(0,12)}}</small></details>
    </template>
    <template v-else><p>这场历史训练尚未生成档案。可根据已有冻结配置与事件补建，保留原始成绩。</p><button type="button" @click="load(true)">补建本场训练档案</button></template>
  </section>
</template>
<style scoped>
.training-archive{padding-block:16px;border-bottom:1px solid #41675b;font-size:16px;line-height:1.7;min-width:0;overflow-wrap:anywhere;}
.training-archive header{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:8px;}
.training-archive h3{font-size:18px;margin:0;}.training-archive header span{font-size:14px;color:#a5e9c5;}
.training-archive p{margin:10px 0;}.training-archive__actions{display:flex;flex-wrap:wrap;gap:8px;margin-block:12px;}
.training-archive button{min-height:44px;padding:10px 12px;border:1px solid #719b87;border-radius:6px;background:#153f30;color:#e4f1e8;font:inherit;white-space:normal;text-align:center;}
.training-archive button:hover{background:#24563e;}.training-archive button:focus-visible,.training-archive summary:focus-visible{outline:2px solid #9ce3bf;outline-offset:3px;}
.training-archive summary{padding-block:10px;cursor:pointer;min-height:44px;box-sizing:border-box;}
.training-archive ul{padding-left:22px;}.training-archive li{margin-block:8px;}.training-archive small{font-size:14px;line-height:1.7;color:#b7cfbf;}
</style>
