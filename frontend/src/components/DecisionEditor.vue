<script setup lang="ts">
import { createApiClient } from '../api/client'

import { onMounted, ref } from 'vue'
import AppIcon from './AppIcon.vue'

const props = defineProps<{ apiBaseUrl: string; accessToken: string; sceneId: string }>()
const api = createApiClient(props.apiBaseUrl, () => props.accessToken)
const emit = defineEmits<{ close: [] }>()
type Point = { id: string; name: string; responsible_role: string; time_limit_seconds: number; trigger_condition: string; options: Array<{ id: string; label: string; consequence: string }> }
type Task = { id: string; title: string; target: string; deadline_seconds: number; status: string }
const points = ref<Point[]>([])
const tasks = ref<Task[]>([])
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const form = ref({ name: '是否启动社区响应', trigger_condition: '确认充电棚火情后', responsible_role: '应急指挥人员', time_limit_seconds: 30, options: [{ label: '立即启动响应', consequence: '通知物业并派发初始处置任务' }, { label: '继续观察', consequence: '延迟响应，风险等级上升' }] })
async function load() {
  loading.value = true; error.value = ''
  try { points.value = await api.get<Point[]>(`/scenes/${props.sceneId}/decision-points`) }
  catch (caught) { error.value = caught instanceof Error ? caught.message : '决策点加载失败。' }
  finally { loading.value = false }
}
async function save() {
  busy.value = true; error.value = ''; notice.value = ''
  try { const body = await api.post<Point>(`/scenes/${props.sceneId}/decision-points`,form.value); points.value.push(body); notice.value = `已保存“${body.name}”，导演台运行时可触发两个处置分支。` }
  catch (caught) { error.value = caught instanceof Error ? caught.message : '决策点保存失败。' }
  finally { busy.value = false }
}
async function execute(optionId: string) {
  busy.value = true; error.value = ''; notice.value = ''
  try { const body = await api.post<Task>(`/decision-options/${optionId}/execute`); tasks.value = [body, ...tasks.value]; notice.value = `已试运行“${body.title}”，任务已进入下方队列。` }
  catch (caught) { error.value = caught instanceof Error ? caught.message : '任务生成失败。' }
  finally { busy.value = false }
}
onMounted(() => void load())
</script>

<template>
  <section class="decision-panel" aria-labelledby="decision-title">
    <div class="decision-intro"><span>STEP 03</span><h2 id="decision-title">决策与任务</h2><p>把关键时刻设计为两个可选择分支，并验证每个选择能否生成可执行任务。</p><button class="text-action icon-action" type="button" @click="emit('close')"><AppIcon name="back" :size="16" />返回基本参数</button></div>
    <div class="decision-body">
      <p v-if="error" class="message message--error" role="alert">{{ error }} <button class="text-action" type="button" @click="load">重试</button></p><p v-if="notice" class="message message--success" role="status">{{ notice }}</p>
      <div class="decision-columns">
        <section class="decision-library" aria-labelledby="decision-library-title"><div class="subheading"><div><span>已配置</span><h3 id="decision-library-title">决策点库</h3></div><strong>{{ points.length }}</strong></div><p v-if="loading" class="decision-empty">正在读取决策流程…</p><div v-else-if="!points.length" class="decision-empty"><AppIcon name="split" :size="24" /><strong>还没有决策点</strong><span>在右侧创建第一个分支，随后可在此试运行。</span></div><div v-else class="point-list"><article v-for="point in points" :key="point.id"><div><span>{{ point.responsible_role }} · {{ point.time_limit_seconds }} 秒</span><h4>{{ point.name }}</h4><p>{{ point.trigger_condition }}</p></div><div class="option-list"><button v-for="(option, index) in point.options" :key="option.id" type="button" :disabled="busy" @click="execute(option.id)"><span>{{ String.fromCharCode(65 + index) }}</span><strong>{{ option.label }}</strong><small>{{ option.consequence }}</small><AppIcon name="arrowRight" :size="16" /></button></div></article></div></section>
        <section class="decision-form-card" aria-labelledby="new-decision-title"><div class="subheading"><div><span>新建</span><h3 id="new-decision-title">编排决策分支</h3></div></div><form class="map-object-form" @submit.prevent="save"><label for="decision-name">决策名称</label><input id="decision-name" v-model="form.name" required maxlength="120" /><label for="decision-trigger">触发条件</label><input id="decision-trigger" v-model="form.trigger_condition" required maxlength="240" /><div class="form-pair"><div><label for="decision-role">负责角色</label><select id="decision-role" v-model="form.responsible_role"><option>应急指挥人员</option><option>物业/网格员</option><option>演练总控/导演</option></select></div><div><label for="decision-limit">限时（秒）</label><input id="decision-limit" v-model.number="form.time_limit_seconds" type="number" min="5" max="600" required /></div></div><fieldset><legend>选项 A · 主动处置</legend><label for="option-a-label">选项名称</label><input id="option-a-label" v-model="form.options[0].label" required /><label for="option-a-consequence">执行后果</label><textarea id="option-a-consequence" v-model="form.options[0].consequence" rows="2" required /></fieldset><fieldset><legend>选项 B · 对照分支</legend><label for="option-b-label">选项名称</label><input id="option-b-label" v-model="form.options[1].label" required /><label for="option-b-consequence">执行后果</label><textarea id="option-b-consequence" v-model="form.options[1].consequence" rows="2" required /></fieldset><button class="primary-button icon-button" type="submit" :disabled="busy"><AppIcon name="plus" :size="18" />{{ busy ? '正在保存…' : '保存决策点' }}</button></form></section>
      </div>
      <section v-if="tasks.length" class="task-preview" aria-labelledby="task-preview-title"><div class="subheading"><div><span>试运行结果</span><h3 id="task-preview-title">动态任务队列</h3></div><strong>{{ tasks.length }}</strong></div><div class="task-preview__list"><article v-for="task in tasks" :key="task.id"><AppIcon name="tasks" :size="18" /><div><strong>{{ task.title }}</strong><span>{{ task.target }}</span></div><time>{{ task.deadline_seconds }} 秒</time></article></div></section>
    </div>
  </section>
</template>

<style scoped>
.decision-panel{display:grid;grid-template-columns:minmax(13rem,.3fr) minmax(0,1fr);gap:clamp(2rem,4vw,4rem);padding:clamp(1.25rem,3vw,2.2rem)}.decision-intro{align-self:start;border-top:2px solid #a24d35;padding-top:.8rem}.decision-intro>span{color:#a24d35;font-size:.7rem;font-weight:750;letter-spacing:.14em}.decision-intro h2{margin:.45rem 0 0;color:#1d2928;font-size:1.65rem}.decision-intro p{margin:.7rem 0 1rem;color:#71807d;font-size:.8rem;line-height:1.65}.icon-action,.icon-button{display:inline-flex;align-items:center;justify-content:center;gap:.42rem}.decision-body{min-width:0}.decision-columns{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(18rem,.75fr);gap:1rem}.decision-library,.decision-form-card,.task-preview{border:1px solid #cad1cd;border-radius:.9rem;background:#fff;padding:1rem}.subheading{display:flex;align-items:end;justify-content:space-between;gap:1rem;border-bottom:1px solid #d9dedb;padding-bottom:.7rem}.subheading span{color:#a24d35;font-size:.64rem;font-weight:750;letter-spacing:.09em}.subheading h3{margin:.18rem 0 0;color:#273332;font-size:.95rem}.subheading>strong{color:#164b49;font-size:1.5rem}.decision-empty{display:grid;justify-items:start;gap:.45rem;margin:1rem 0 0;border:1px dashed #c4cdc8;border-radius:.75rem;padding:1.2rem;color:#55706a;font-size:.76rem}.decision-empty strong,.decision-empty span{display:block}.decision-empty span{color:#71807d}.point-list{display:grid;gap:.9rem;margin-top:1rem}.point-list article{border-bottom:1px solid #d9dedb;padding-bottom:1rem}.point-list article:last-child{border-bottom:0;padding-bottom:0}.point-list h4{margin:.22rem 0 0;color:#253130;font-size:.9rem}.point-list p,.point-list>article>div>span{margin:.25rem 0 0;color:#71807d;font-size:.69rem;line-height:1.5}.option-list{display:grid;gap:.45rem;margin-top:.7rem}.option-list button{display:grid;grid-template-columns:auto 1fr auto;gap:.55rem;align-items:center;width:100%;border:1px solid #cbd3cf;border-radius:.65rem;background:#f7f7f2;color:#2c3937;padding:.58rem;text-align:left}.option-list button:hover:not(:disabled){border-color:#51817a;background:#edf3ef}.option-list button>span{grid-row:span 2;display:grid;place-items:center;width:1.55rem;height:1.55rem;border-radius:50%;background:#173f3e;color:#fff;font-size:.65rem}.option-list strong,.option-list small{display:block}.option-list strong{font-size:.74rem}.option-list small{color:#71807d;font-size:.63rem}.option-list svg{grid-column:3;grid-row:1/3}.decision-form-card .map-object-form{margin-top:.6rem}.decision-form-card fieldset{display:grid;gap:.5rem;margin:.55rem 0 0;border:1px solid #d5dbd7;border-radius:.7rem;padding:.65rem}.decision-form-card legend{padding:0 .25rem;color:#465251;font-size:.72rem;font-weight:700}.form-pair{display:grid;grid-template-columns:1fr 1fr;gap:.6rem}.form-pair>div{display:grid;gap:.55rem}.decision-form-card textarea{resize:vertical}.decision-form-card .primary-button{margin-top:.4rem}.task-preview{margin-top:1rem}.task-preview__list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.55rem;margin-top:.75rem}.task-preview__list article{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:.55rem;border:1px solid #d5dbd7;border-radius:.65rem;padding:.65rem;color:#164b49}.task-preview__list strong,.task-preview__list span{display:block}.task-preview__list strong{font-size:.72rem}.task-preview__list span{margin-top:.15rem;color:#71807d;font-size:.63rem}.task-preview__list time{color:#a24d35;font-size:.68rem;font-weight:700}@media(max-width:1100px){.decision-panel,.decision-columns{grid-template-columns:1fr}}@media(max-width:600px){.form-pair,.task-preview__list{grid-template-columns:1fr}.decision-panel{padding:1rem}}
</style>
