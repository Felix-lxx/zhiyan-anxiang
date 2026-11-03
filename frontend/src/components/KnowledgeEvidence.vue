<script setup lang="ts">
import type { KnowledgeResult } from '../domain/knowledge'
import KnowledgeObservation from './KnowledgeObservation.vue'
import KnowledgeApplicability from './KnowledgeApplicability.vue'
defineProps<{ result: KnowledgeResult }>()
const emit=defineEmits<{open:[source:{documentId:string;versionId:string}]}>()
const category = (value: string) => ({ official_summary: '官方资料摘要', platform_guide: '项目训练说明',experience:'组织者发布的复盘经验' }[value] || '用户发布资料')
</script>
<template>
  <section class="knowledge-evidence" aria-label="检索依据">
    <p>{{result.notice}}</p><p v-if="!result.hits.length">没有命中适用资料，请补充关键词或社区预案。</p>
    <p v-if="result.retrieved_at">检索时刻：{{new Date(result.retrieved_at).toLocaleString('zh-CN')}}。以下保留当时命中的版本。</p>
    <details v-for="hit in result.hits" :key="hit.chunk_id">
      <summary>[{{hit.id}}] {{hit.title}} <span>V{{hit.version}} · {{category(hit.category)}}</span></summary>
      <p>{{hit.publisher}} · {{hit.anchor}}</p><blockquote>{{hit.content}}</blockquote>
      <KnowledgeObservation v-if="hit.experience" :source="hit.experience" compact/>
      <KnowledgeApplicability v-if="hit.applicability" :value="hit.applicability"/>
      <button type="button" @click="emit('open',{documentId:hit.document_id,versionId:hit.version_id})">核对这份资料的引用版本</button>
      <a v-if="hit.source_url" :href="hit.source_url" target="_blank" rel="noopener noreferrer">打开官方来源</a>
      <small>片段校验：{{hit.content_hash.slice(0,12)}}</small>
    </details>
  </section>
</template>
<style scoped>
.knowledge-evidence { min-width:0; font-size:16px; }
.knowledge-evidence>p { font-size:14px; line-height:1.7; }
details { padding:12px 0; border-top:1px solid currentColor; }
summary { cursor:pointer; font-size:16px; line-height:1.7; overflow-wrap:anywhere; }
summary span,small,details>p { display:block; font-size:14px; line-height:1.7; opacity:.85; }
blockquote { margin:12px 0; padding:0 0 0 12px; border-left:3px solid #7cae9b; white-space:pre-wrap; overflow-wrap:anywhere; line-height:1.8; }
a { display:inline-flex; min-height:44px; align-items:center; text-decoration:underline; color:inherit; }
button{min-height:44px;padding:8px 12px;border:1px solid currentColor;border-radius:8px;background:transparent;color:inherit;font:inherit;white-space:normal;cursor:pointer;}
</style>
