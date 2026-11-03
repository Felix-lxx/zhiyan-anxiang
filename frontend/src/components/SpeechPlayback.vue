<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'

const props=defineProps<{text:string;active:boolean;label?:string}>()
const supported=typeof window.speechSynthesis!=='undefined' && typeof SpeechSynthesisUtterance!=='undefined'
const playing=ref(false), error=ref('')
let current:SpeechSynthesisUtterance|null=null, epoch=0
function stop(){const owned=!!current;epoch++;current=null;playing.value=false;if(supported&&owned)window.speechSynthesis.cancel()}
function play(){
  if(!supported||!props.active)return
  if(playing.value){stop();return}
  stop();error.value='';playing.value=true
  const generation=epoch
  const text=props.text.replace(/\[[SK]\d+\]/g,'').slice(0,6000)
  const parts=text.match(/[^。！？\n]{1,180}[。！？\n]?/g)||[]
  const next=(index:number)=>{
    if(generation!==epoch)return
    if(index>=parts.length){playing.value=false;current=null;return}
    const utterance=new SpeechSynthesisUtterance(parts[index])
    utterance.lang='zh-CN';utterance.rate=1;current=utterance
    utterance.onend=()=>next(index+1)
    utterance.onerror=()=>{if(generation===epoch){playing.value=false;current=null;error.value='浏览器朗读未完成，可继续阅读文字。'}}
    window.speechSynthesis.speak(utterance)
  }
  next(0)
}
watch([()=>props.text,()=>props.active],stop)
onBeforeUnmount(stop)
</script>

<template>
  <div v-if="supported" class="speech-playback">
    <button type="button" :aria-pressed="playing" :disabled="!active||!text" @click="play"><AppIcon :name="playing?'stop':'volume'" :size="18"/>{{playing?'停止朗读':label||'朗读这条回答'}}</button>
    <small>{{error||'使用浏览器语音朗读，声音由设备和浏览器提供。'}}</small>
  </div>
</template>

<style scoped>
.speech-playback{display:flex;align-items:center;gap:8px 16px;flex-wrap:wrap;margin:12px 0;}
.speech-playback button{display:inline-flex;align-items:center;gap:8px;min-height:44px;padding:8px 12px;border:1px solid #79a69d;border-radius:8px;background:#163f37;color:#e9f6f0;font:inherit;cursor:pointer;}
.speech-playback small{font-size:14px;line-height:1.6;color:#bcd3ca;}
.speech-playback button:focus-visible{outline:2px solid #a5e2cd;outline-offset:3px;}
</style>
