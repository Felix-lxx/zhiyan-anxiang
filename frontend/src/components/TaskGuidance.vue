<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { createApiClient } from '../api/client'
import type { ExerciseTask } from '../domain/task'
import type { KnowledgeDocument, KnowledgeVersion } from '../domain/knowledge'
import type { TaskGuidanceSnapshot } from '../domain/task-guidance'
import KnowledgeEvidence from './KnowledgeEvidence.vue'
import KnowledgeReader from './KnowledgeReader.vue'

const props=defineProps<{apiBaseUrl:string;accessToken:string;drillId:string;task:ExerciseTask;elapsedSeconds:number;historical?:boolean;autoOpen?:boolean}>()
const emit=defineEmits<{locate:[]}>()
const api=createApiClient(props.apiBaseUrl,()=>props.accessToken)
const opened=ref(false),busy=ref(false),referenceBusy=ref(false),error=ref('')
const data=ref<TaskGuidanceSnapshot|null>(null),reference=ref<{title:string;version:KnowledgeVersion;chunkId:string}|null>(null)
const referencePanel=ref<HTMLElement|null>(null),panel=ref<HTMLDetailsElement|null>(null)
let generation=0,controller:AbortController|undefined
const stale=computed(()=>Boolean(data.value&&(props.elapsedSeconds-data.value.observed_at_seconds>15||props.task.status!==data.value.task.status||props.task.assignee_id!==data.value.task.assignee_id||Boolean(props.task.verification_ready)!==Boolean(data.value.task.verification_ready))))
const clock=(value:number)=>String(Math.floor(value/60)).padStart(2,'0')+':'+String(Math.floor(value%60)).padStart(2,'0')
async function load(){
  if(busy.value||props.historical)return
  const version=++generation;controller?.abort();const request=new AbortController();controller=request
  busy.value=true;error.value='';reference.value=null
  const timeout=window.setTimeout(()=>request.abort(),15000)
  try{
    const result=await api.post<TaskGuidanceSnapshot>(`/drills/${props.drillId}/tasks/${props.task.id}/guidance`,{},{signal:request.signal})
    if(version===generation)data.value=result
  }catch(cause){if(version===generation)error.value=cause instanceof Error?cause.message:'任务依据读取失败，请重试。'}
  finally{window.clearTimeout(timeout);if(version===generation)busy.value=false}
}
function toggle(event:Event){opened.value=(event.target as HTMLDetailsElement).open;if(opened.value&&!data.value&&!busy.value&&!props.historical)void load()}
async function closeReference(){
  const chunkId=reference.value?.chunkId;reference.value=null
  await nextTick()
  const cited=chunkId?panel.value?.querySelector<HTMLDetailsElement>(`details[data-knowledge-chunk="${CSS.escape(chunkId)}"]`):null
  if(cited)cited.open=true
  ;(cited?.querySelector<HTMLButtonElement>('button')??panel.value?.querySelector<HTMLElement>('summary'))?.focus({preventScroll:true})
}
async function openReference(source:{documentId:string;versionId:string;chunkId:string}){
  if(referenceBusy.value)return
  const version=++generation;controller?.abort();const request=new AbortController();controller=request
  referenceBusy.value=true;error.value=''
  const timeout=window.setTimeout(()=>request.abort(),10000)
  try{
    const document=await api.get<KnowledgeDocument>('/knowledge/documents/'+source.documentId,{signal:request.signal})
    const pinned=document.versions.find(item=>item.id===source.versionId)
    if(!pinned?.chunks?.some(chunk=>chunk.id===source.chunkId))throw new Error('引用片段已不可访问，请核对原检索记录。')
    if(version!==generation)return
    reference.value={title:document.title,version:pinned,chunkId:source.chunkId}
    await nextTick();referencePanel.value?.focus({preventScroll:true})
  }catch(cause){if(version===generation)error.value=cause instanceof Error?cause.message:'资料读取失败。'}
  finally{window.clearTimeout(timeout);if(version===generation)referenceBusy.value=false}
}
watch(()=>props.autoOpen,value=>{if(value){opened.value=true;void load()}},{immediate:true})
watch([()=>props.drillId,()=>props.task.id,()=>props.historical],()=>{generation++;controller?.abort();data.value=null;reference.value=null;busy.value=false;referenceBusy.value=false;error.value='';if(opened.value&&!props.historical)void load()})
onBeforeUnmount(()=>{generation++;controller?.abort()})
</script>
<template>
  <details ref="panel" class="task-guidance" :open="opened" @toggle="toggle">
    <summary>处置依据与核验条件</summary>
    <p v-if="historical">当前为历史回放，核验状态以回放任务和原计划引用为准，不查询实时任务依据。</p>
    <template v-else>
      <div v-if="!reference" class="task-guidance__actions"><button type="button" :disabled="busy||referenceBusy" @click="load">{{data?'更新任务依据':'重新读取依据'}}</button><button v-if="task.target_position||task.target_device_id" type="button" @click="emit('locate')">定位任务对象</button></div>
      <p v-if="error" role="alert">{{error}}</p>
      <p v-if="busy||referenceBusy" role="status">{{referenceBusy?'正在核对引用版本…':'正在核对任务与适用资料…'}}</p>
      <template v-if="reference">
        <section ref="referencePanel" tabindex="-1" aria-label="任务引用原文">
          <button type="button" @click="closeReference">返回任务依据</button>
          <h4>{{reference.title}} · V{{reference.version.number}}</h4>
          <KnowledgeReader :chunks="reference.version.chunks??[]" :focus-chunk-id="reference.chunkId"/>
        </section>
      </template>
      <template v-else-if="data">
        <p class="task-guidance__snapshot">现场读取于 {{clock(data.observed_at_seconds)}} · 事件序号 {{data.event_sequence}}</p>
        <p v-if="stale" class="task-guidance__stale" role="status">现场或任务已变化，以下保留查询时的状态；操作前更新依据。</p>
        <h4>下一步</h4><p>{{data.next_action.label}}</p>
        <ol class="task-guidance__conditions"><li v-for="item in data.conditions" :key="item.id"><strong>{{item.label}} · {{item.met?'已满足':'待完成'}}</strong><p>{{item.detail}}</p></li></ol>
        <details v-if="data.steps.length"><summary>任务约定步骤</summary><ol><li v-for="(step,index) in data.steps" :key="index">{{step}}</li></ol></details>
        <p>知识资料提供参考，任务是否可核验仍由本场规则与责任证据确认。</p>
        <KnowledgeEvidence :result="data.knowledge" @open="openReference"/>
      </template>
    </template>
  </details>
</template>
<style scoped>
.task-guidance { margin-block:18px; padding-block:12px; border-block:1px solid var(--border-default,#537968); min-width:0; }
.task-guidance summary { min-height:44px; cursor:pointer; line-height:1.7; font-size:16px; font-weight:600; }
.task-guidance h4 { font-size:16px; margin:16px 0 8px; overflow-wrap:anywhere; }
.task-guidance p,.task-guidance li { font-size:16px; line-height:1.75; overflow-wrap:anywhere; }
.task-guidance .task-guidance__snapshot,.task-guidance__conditions p { font-size:14px; }
.task-guidance__conditions { padding-left:22px; }
.task-guidance__conditions li { padding-block:8px; }
.task-guidance__conditions p { margin:4px 0; }
.task-guidance__stale { color:#f2d99c; }
.task-guidance__actions { display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }
.task-guidance button { min-height:44px; padding:10px 12px; font:inherit; color:inherit; background:transparent; border:1px solid currentColor; border-radius:6px; cursor:pointer; }
.task-guidance button:disabled { opacity:.55; cursor:default; }
.task-guidance :focus-visible { outline:2px solid currentColor; outline-offset:3px; }
.task-guidance :deep(.knowledge-reader article[data-cited=true]),.task-guidance :deep(.knowledge-reader__reference) { background:#183e31; color:#e6f1e8; }
.task-guidance :deep(.knowledge-reader__continuous) { display:flex; align-items:center; gap:8px; }
</style>
