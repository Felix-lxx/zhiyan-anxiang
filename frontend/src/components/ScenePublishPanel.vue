<script setup lang="ts">
import { createApiClient } from '../api/client'

import { computed, ref } from 'vue'
import AppIcon from './AppIcon.vue'

const props = defineProps<{ apiBaseUrl: string; accessToken: string; sceneId: string; sceneStatus: string; versionNumber: number }>()
const api = createApiClient(props.apiBaseUrl, () => props.accessToken)
const emit = defineEmits<{ published: [] }>()
const feedback = ref('')
const feedbackKind = ref<'success' | 'warning' | 'error'>('success')
const issues = ref<string[]>([])
const busyAction = ref<'validate' | 'publish' | ''>('')
const validated = ref(false)
const published = ref(props.sceneStatus === 'published')
const canPublish = computed(() => validated.value && !busyAction.value && !published.value)

async function request(path: 'validate' | 'publish') {
  return api.post<Record<string,unknown>>(`/scenes/${props.sceneId}/${path}`)
}

async function validateScene() {
  busyAction.value = 'validate'; feedback.value = ''; issues.value = []; validated.value = false
  try {
    const payload = await request('validate')
    issues.value = Array.isArray(payload.issues) ? payload.issues.filter((item): item is string => typeof item === 'string') : []
    validated.value = payload.passed === true && issues.value.length === 0
    feedback.value = typeof payload.message === 'string' ? payload.message : validated.value ? '场景校验通过，可以发布。' : '场景尚不能发布。'
    feedbackKind.value = validated.value ? 'success' : 'warning'
  } catch (caught) {
    feedback.value = caught instanceof Error ? caught.message : '完整性校验失败。'
    feedbackKind.value = 'error'
  } finally { busyAction.value = '' }
}

async function publishScene() {
  if (!canPublish.value) return
  busyAction.value = 'publish'; feedback.value = ''
  try {
    const payload = await request('publish')
    feedback.value = typeof payload.message === 'string' ? payload.message : '场景已发布。'
    feedbackKind.value = 'success'; published.value = true; emit('published')
  } catch (caught) {
    feedback.value = caught instanceof Error ? caught.message : '场景发布失败。'
    feedbackKind.value = 'error'
  } finally { busyAction.value = '' }
}
</script>

<template>
  <section class="publish-panel" aria-labelledby="publish-title">
    <div class="publish-intro"><span>STEP 04</span><h2 id="publish-title">校验与发布</h2><p>先校验当前版本的完整性，再冻结为导演台可选择的运行版本。</p></div>
    <div class="release-card">
      <div class="release-card__header"><div class="release-icon" :data-ready="validated || published"><AppIcon :name="published ? 'lock' : validated ? 'check' : 'inspect'" :size="26" /></div><div><span>待发布版本</span><strong>场景版本 V{{ versionNumber }}</strong><small>{{ published ? '已冻结，可用于创建演练场次' : validated ? '校验通过，等待发布' : '尚未执行本次完整性校验' }}</small></div><span class="release-status" :data-state="published ? 'published' : validated ? 'ready' : 'pending'">{{ published ? '已发布' : validated ? '可发布' : '待校验' }}</span></div>
      <div class="validation-list" aria-label="发布条件">
        <div :data-ok="validated || published"><AppIcon :name="validated || published ? 'check' : 'clock'" :size="16" /><span>火源、时间、风向与居民规模</span></div>
        <div :data-ok="published"><AppIcon :name="published ? 'check' : 'lock'" :size="16" /><span>版本冻结与运行授权</span></div>
      </div>
      <div class="publish-actions"><button class="secondary-button icon-button" type="button" :disabled="!!busyAction || published" @click="validateScene"><AppIcon name="inspect" :size="18" />{{ busyAction === 'validate' ? '校验中…' : '运行完整性校验' }}</button><button class="primary-button icon-button" type="button" :disabled="!canPublish" @click="publishScene"><AppIcon name="lock" :size="18" />{{ busyAction === 'publish' ? '发布中…' : published ? '已发布' : '发布当前版本' }}</button></div>
      <div v-if="feedback" class="publish-feedback" :data-kind="feedbackKind" :role="feedbackKind === 'error' ? 'alert' : 'status'"><AppIcon :name="feedbackKind === 'error' ? 'help' : feedbackKind === 'warning' ? 'clock' : 'check'" :size="18" /><div><strong>{{ feedbackKind === 'error' ? '操作失败' : feedbackKind === 'warning' ? '需要补充' : '操作完成' }}</strong><p>{{ feedback }}</p></div></div>
      <ul v-if="issues.length" class="issue-list"><li v-for="issue in issues" :key="issue">{{ issue }}</li></ul>
    </div>
  </section>
</template>

<style scoped>
.publish-panel{display:grid;grid-template-columns:minmax(13rem,.38fr) minmax(0,1fr);gap:clamp(2rem,5vw,5rem);padding:clamp(1.25rem,3vw,2.2rem)}.publish-intro{align-self:start;border-top:2px solid #a24d35;padding-top:.8rem}.publish-intro>span{color:#a24d35;font-size:.7rem;font-weight:750;letter-spacing:.14em}.publish-intro h2{margin:.45rem 0 0;color:#1d2928;font-size:1.65rem}.publish-intro p{margin:.7rem 0 0;color:#71807d;font-size:.8rem;line-height:1.65}.release-card{border:1px solid #c7cfcb;border-radius:.9rem;background:#fff;padding:1.2rem}.release-card__header{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:.9rem}.release-icon{display:grid;place-items:center;width:3rem;height:3rem;border:1px solid #c59b80;border-radius:50%;background:#fbede4;color:#8a351f}.release-icon[data-ready="true"]{border-color:#89aa9a;background:#e4f4ec;color:#14543f}.release-card__header span,.release-card__header strong,.release-card__header small{display:block}.release-card__header>div span,.release-card__header small{color:#71807d;font-size:.68rem}.release-card__header strong{margin:.16rem 0;color:#263130;font-size:.95rem}.release-status{border:1px solid #c7cfcb;border-radius:999px;padding:.25rem .55rem;color:#65736f;font-size:.67rem}.release-status[data-state="ready"],.release-status[data-state="published"]{border-color:#8eb4a1;background:#e4f4ec;color:#14543f}.validation-list{display:grid;gap:.55rem;margin-top:1.2rem;border-top:1px solid #d8ddd9;padding-top:1rem}.validation-list>div{display:flex;align-items:center;gap:.55rem;color:#71807d;font-size:.76rem}.validation-list>div[data-ok="true"]{color:#14543f}.publish-actions{display:flex;justify-content:flex-end;gap:.7rem;margin-top:1.2rem}.publish-actions button{min-height:2.7rem;margin:0}.icon-button{display:inline-flex;align-items:center;justify-content:center;gap:.42rem}.publish-feedback{display:flex;gap:.65rem;margin-top:1rem;border:1px solid #a7c8b8;border-radius:.65rem;background:#e8f4ed;padding:.8rem;color:#14543f}.publish-feedback[data-kind="warning"]{border-color:#d4b47f;background:#fff2da;color:#78521b}.publish-feedback[data-kind="error"]{border-color:#d09988;background:#fdeae4;color:#7d2e1b}.publish-feedback strong,.publish-feedback p{display:block;margin:0;font-size:.75rem}.publish-feedback p{margin-top:.2rem;line-height:1.5}.issue-list{margin:.7rem 0 0;padding-left:1.2rem;color:#7d2e1b;font-size:.74rem;line-height:1.7}@media(max-width:900px){.publish-panel{grid-template-columns:1fr}}@media(max-width:540px){.release-card__header{grid-template-columns:auto 1fr}.release-status{grid-column:2}.publish-actions{align-items:stretch;flex-direction:column}.publish-actions button{width:100%}}
</style>
