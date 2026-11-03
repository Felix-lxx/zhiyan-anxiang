<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { createApiClient } from '../api/client'
import { PcmRecorder } from '../audio/recorder'
import AppIcon from './AppIcon.vue'

const props = defineProps<{ apiBaseUrl: string; accessToken: string; disabled?: boolean; destination?: string; tone?:'light'|'dark' }>()
const emit = defineEmits<{ transcript: [text: string]; activity:[active:boolean] }>()
const api = createApiClient(props.apiBaseUrl, () => props.accessToken)
const configured = ref(false), loading = ref(true), seconds = ref(0), error = ref('')
const state = ref<'idle' | 'permission' | 'recording' | 'transcribing'>('idle')
const lastTranscript = ref('')
const level=ref(0), heardInput=ref(false)
watch(state, value => emit('activity', value !== 'idle'))
let recorder: PcmRecorder | undefined, timer: ReturnType<typeof setInterval> | undefined
let request: AbortController | undefined, generation = 0
function cancel() {
  generation++
  clearInterval(timer)
  recorder?.cancel(); recorder = undefined
  request?.abort(); request = undefined
  state.value = 'idle'
  level.value=0
}
async function start() {
  if (state.value !== 'idle' || !configured.value) return
  const current = ++generation
  error.value = ''; seconds.value = 0; level.value=0;heardInput.value=false; state.value = 'permission'
  const capture = new PcmRecorder(() => { if (current === generation) void finish() },value=>{
    if(current!==generation)return
    level.value=value
    if(value>12)heardInput.value=true
  }); recorder = capture
  try {
    await capture.start()
    if (current !== generation) return
    state.value = 'recording'
    const started = performance.now()
    timer = setInterval(() => {
      seconds.value = Math.min(30, Math.floor((performance.now() - started) / 1000))
      if (seconds.value >= 30) void finish()
    }, 200)
  } catch (cause) {
    if (current !== generation) return
    cancel()
    error.value = cause instanceof DOMException && cause.name === 'NotAllowedError'
      ? '未获得麦克风权限，请在浏览器地址栏允许后重试。'
      : cause instanceof Error ? cause.message : '无法打开麦克风。'
  }
}
async function finish() {
  if (state.value !== 'recording' || !recorder) return
  const current = generation, capture = recorder
  clearInterval(timer)
  state.value = 'transcribing'
  try {
    const audio = await capture.finish()
    if (current !== generation) return
    const abort = new AbortController(); request = abort
    const result = await api.post<{ text: string }>('/speech/transcribe', audio, { signal: abort.signal })
    if (current === generation) { lastTranscript.value=result.text; emit('transcript', result.text); state.value = 'idle' }
  } catch (cause) {
    if (current === generation) { error.value = cause instanceof Error ? cause.message : '听写失败，请重试。'; state.value = 'idle' }
  } finally {
    capture.cancel()
    if (current === generation) { recorder = undefined; request = undefined }
  }
}
watch(() => props.disabled, disabled => { if (disabled) cancel() })
onMounted(async () => {
  const abort = new AbortController(); request = abort
  try { const status = await api.get<{ configured: boolean }>('/speech/status', { signal: abort.signal }); configured.value = status.configured }
  catch { error.value = '语音服务状态读取失败，仍可直接输入文字。' }
  finally { loading.value = false; if (request === abort) request = undefined }
})
onBeforeUnmount(() => { cancel(); emit('activity',false) })
</script>

<template>
  <div class="speech-input" :data-tone="tone||'dark'" aria-label="语音输入" :aria-busy="state!=='idle'">
    <div class="speech-input__controls">
      <button v-if="state==='idle'" type="button" :disabled="disabled || loading || !configured" @click="start"><AppIcon name="microphone" :size="18"/>{{ loading ? '检查语音服务…' : '语音输入' }}</button>
      <button v-else-if="state==='recording'" type="button" class="speech-input__recording" @click="finish"><AppIcon name="stop" :size="18"/>结束并识别 · {{ seconds }}s</button>
      <span v-else role="status">{{ state==='permission' ? '正在请求麦克风…' : '讯飞正在转写…' }}</span>
      <button v-if="state!=='idle'" type="button" @click="cancel">取消</button>
    </div>
    <progress v-if="state==='recording'" :value="seconds" max="30" aria-label="录音时长，最多30秒" />
    <div v-if="state==='recording'" class="speech-input__level"><span>麦克风输入</span><meter min="0" max="100" :value="level" aria-label="麦克风相对输入音量"/><span>{{level>12?'已接收声音':'输入较弱'}}</span></div>
    <p v-if="state==='recording'&&seconds>=4&&!heardInput" role="status">尚未检测到明显输入，请靠近麦克风或检查设备。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-else-if="state==='recording'" role="status">正在录音 {{seconds}} / 30 秒。结束后发送至讯飞转写；取消则不上传。</p>
    <p v-else-if="lastTranscript && state==='idle'" role="status">已填入{{destination || '提问框'}}，请核对并编辑，再确认提交。</p>
    <p v-else role="status">{{ !configured && !loading ? '语音服务未配置，可继续输入文字。' : `最长 30 秒；转写填入${destination || '提问框'}，不会自动发送或执行。` }}</p>
  </div>
</template>

<style scoped>
.speech-input { display:grid; gap:6px; margin:8px 0; min-width:0; }
.speech-input__controls { display:flex; flex-wrap:wrap; align-items:center; gap:8px; }
.speech-input__controls button { display:inline-flex; align-items:center; justify-content:center; gap:8px; min-height:44px; padding:8px 12px; border:1px solid #79a69d; border-radius:8px; background:#163f37; color:#e9f6f0; font-size:16px; cursor:pointer; }
.speech-input__controls button:disabled { opacity:.5; cursor:default; }
.speech-input__controls .speech-input__recording { background:#603d30; border-color:#e9ab82; }
.speech-input p,.speech-input__controls>span { margin:0; color:#bcd3ca; font-size:14px; line-height:1.6; overflow-wrap:anywhere; }
.speech-input p[role='alert'] { color:#ffd1ba; }
.speech-input button:focus-visible { outline:2px solid #a5e2cd; outline-offset:3px; }
.speech-input progress {width:100%;height:6px;accent-color:#7bd8bd;}
.speech-input__level{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;font-size:14px;line-height:1.6;color:#bcd3ca;}
.speech-input__level meter{flex:1 1 80px;min-width:60px;max-width:160px;height:12px;accent-color:#7bd8bd;}
.speech-input[data-tone=light] .speech-input__level{color:#375f51;}
.speech-input[data-tone=light] p,.speech-input[data-tone=light] .speech-input__controls>span {color:#375f51;}
.speech-input[data-tone=light] p[role=alert] {color:#893b23;}
</style>
