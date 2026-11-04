<script setup lang="ts">
import type { KnowledgeMatch } from '../domain/knowledge'
defineProps<{ value: KnowledgeMatch }>()
const methods = { keyword:'关键词命中', semantic:'语义召回', hybrid:'关键词与语义命中' }
</script>
<template>
  <div class="knowledge-match" aria-label="资料匹配线索">
    <p><strong>{{methods[value.method]}}</strong><template v-if="value.terms.length"> · {{value.terms.join('、')}}</template></p>
    <p v-if="value.expanded_terms.length">扩展线索：{{value.expanded_terms.join('、')}}</p>
    <p v-if="value.method==='semantic'&&!value.terms.length">此片段由语义相似检索召回，请核对原文是否回答当前问题。</p>
  </div>
</template>
<style scoped>
.knowledge-match { margin-block:12px; min-width:0; }
.knowledge-match p { margin:4px 0; font-size:14px; line-height:1.7; overflow-wrap:anywhere; }
</style>
