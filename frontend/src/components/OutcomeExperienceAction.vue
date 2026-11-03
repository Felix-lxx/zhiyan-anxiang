<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { createApiClient } from '../api/client'
import type { KnowledgeDocument } from '../domain/knowledge'
const props=defineProps<{apiBaseUrl:string;accessToken:string;runId:string;revision:number;eligible:boolean}>()
const emit=defineEmits<{open:[documentId:string]}>()
const api=createApiClient(props.apiBaseUrl,()=>props.accessToken)
const busy=ref(false),error=ref(''),documentId=ref(''),notice=ref('')
let generation=0
onBeforeUnmount(()=>{generation++})
watch([()=>props.runId,()=>props.revision],()=>{generation++;busy.value=false;error.value='';documentId.value='';notice.value=''})
async function save(){
  if(busy.value||!props.eligible)return
  busy.value=true;error.value='';const current=++generation
  try{
    const result=await api.post<{created:boolean;document:KnowledgeDocument}>('/knowledge/experiences',
      {run_id:props.runId,revision:props.revision})
    if(current!==generation)return
    documentId.value=result.document.id
    notice.value=result.created?'经验草稿已保存；审核发布后才参与检索。':'此观察已有经验资料，可继续核对来源与版本。'
  }catch(cause){if(current===generation)error.value=cause instanceof Error?cause.message:'经验草稿未保存，请重试。'}
  finally{if(current===generation)busy.value=false}
}
</script>
<template>
  <section class="outcome-experience" aria-label="复盘经验入库">
    <h4>把这次观察带到下一次训练</h4>
    <p>保存预测、实际指标和事件依据，补充发现与适用条件，审核后进入本社区知识库。</p>
    <button v-if="!documentId" type="button" :disabled="busy||!eligible" @click="save">{{busy?'正在保存观察依据…':'保存为经验草稿'}}</button>
    <button v-else type="button" @click="emit('open',documentId)">打开经验资料与审核</button>
    <p v-if="!eligible">本次观察不具备完整比较条件，请在完成结果核对后再生成经验。</p>
    <p v-if="notice" role="status">{{notice}}</p><p v-if="error" role="alert">{{error}}</p>
  </section>
</template>
<style scoped>
.outcome-experience{margin-top:16px;padding-top:16px;border-top:1px solid #476653;font-size:16px;line-height:1.7;min-width:0;}
.outcome-experience h4{font-size:18px;margin:0 0 8px;}.outcome-experience p{margin:8px 0;overflow-wrap:anywhere;}
.outcome-experience button{min-height:44px;padding:10px 14px;white-space:normal;background:#194b3e;color:#edf5e7;border:1px solid #79a69d;border-radius:8px;font:inherit;cursor:pointer;}
.outcome-experience button:disabled{opacity:.55;cursor:default;}.outcome-experience p[role=alert]{color:#ffd1ba;}
</style>
