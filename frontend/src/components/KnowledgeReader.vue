<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { KnowledgeChunk } from '../domain/knowledge'

const props = defineProps<{ chunks: KnowledgeChunk[]; focusChunkId?: string }>()
const root = ref<HTMLElement | null>(null)
const activeId = ref(''), continuous = ref(false)
const activeIndex = computed(() => props.chunks.findIndex(chunk => chunk.id === activeId.value))
const visibleChunks = computed(() => continuous.value ? props.chunks : props.chunks.filter(chunk => chunk.id === activeId.value))
async function focusActive() {
  await nextTick()
  const article = [...(root.value?.querySelectorAll<HTMLElement>('[data-chunk]') ?? [])].find(item => item.dataset.chunk === activeId.value)
  article?.focus({ preventScroll: true })
  article?.scrollIntoView({ block: 'nearest', behavior: 'instant' })
}
watch([() => props.chunks, () => props.focusChunkId], ([chunks, focus]) => {
  activeId.value = chunks.some(chunk => chunk.id === focus) ? focus! : chunks[0]?.id ?? ''
  continuous.value = false
  if (focus && focus === activeId.value) void focusActive()
}, { immediate: true })
function move(delta: number) {
  const chunk = props.chunks[activeIndex.value + delta]
  if (chunk) { activeId.value = chunk.id; void focusActive() }
}
</script>
<template>
  <section ref="root" class="knowledge-reader" aria-label="版本正文">
    <p v-if="!chunks.length">此版本没有有效正文，请修订资料。</p>
    <template v-else>
      <div v-if="chunks.length > 1" class="knowledge-reader__navigation">
        <label>阅读位置<select v-model="activeId" aria-label="阅读位置" @change="focusActive"><option v-for="(chunk,index) in chunks" :key="chunk.id" :value="chunk.id">{{index+1}} / {{chunks.length}} · {{chunk.anchor}}</option></select></label>
        <div><button type="button" :disabled="activeIndex<=0" @click="move(-1)">上一段</button><button type="button" :disabled="activeIndex>=chunks.length-1" @click="move(1)">下一段</button></div>
        <label class="knowledge-reader__continuous"><input v-model="continuous" type="checkbox"/>连续阅读全部 {{chunks.length}} 段</label>
      </div>
      <p v-if="focusChunkId&&activeId===focusChunkId" class="knowledge-reader__reference" role="status">已定位检索引用片段 · 第 {{activeIndex+1}} / {{chunks.length}} 段</p>
      <article v-for="chunk in visibleChunks" :key="chunk.id" :data-chunk="chunk.id" :aria-current="chunk.id===activeId?'location':undefined" :data-cited="chunk.id===focusChunkId" tabindex="-1">
        <h3>{{chunk.anchor}}</h3><p>{{chunk.content}}</p><small>内容校验 {{chunk.content_hash.slice(0,12)}}</small>
      </article>
    </template>
  </section>
</template>
<style scoped>
.knowledge-reader { margin-top:24px; min-width:0; }
.knowledge-reader__navigation { display:flex; flex-wrap:wrap; gap:12px; align-items:end; border-block:1px solid #c9d5ca; padding-block:16px; }
.knowledge-reader__navigation>label:first-child { flex:1 1 240px; min-width:0; }
.knowledge-reader__navigation select { width:100%; min-width:0; }
.knowledge-reader__navigation>div { display:flex; gap:8px; flex-wrap:wrap; }
.knowledge-reader__continuous { flex-basis:100%; display:flex; align-items:center; gap:8px; min-height:44px; }
.knowledge-reader__continuous input { width:18px; min-height:18px; flex:none; }
.knowledge-reader__reference { padding:12px; background:#e6eee2; color:#173c35; }
.knowledge-reader article { padding:16px 0; border-top:1px solid #c9d5ca; scroll-margin-block:24px; overflow-wrap:anywhere; }
.knowledge-reader article[data-cited=true] { padding:16px; border:1px solid #6c9984; background:#f0f5ed; }
.knowledge-reader article:focus-visible { outline:2px solid #276d56; outline-offset:3px; }
.knowledge-reader article p { white-space:pre-wrap; font-size:16px; line-height:1.85; }
.knowledge-reader small { font-size:14px; line-height:1.7; }
@media(max-width:480px) { .knowledge-reader__navigation>div { width:100%; } .knowledge-reader__navigation>div button { flex:1; } }
</style>
