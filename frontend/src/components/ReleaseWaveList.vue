<script setup lang="ts">
import {computed} from 'vue'
import type {ReleaseWave} from '../domain/agent'
import AppIcon from './AppIcon.vue'

const props=defineProps<{waves:ReleaseWave[];historical?:boolean}>()
const emit=defineEmits<{passage:[id:string];resident:[id:string];building:[id:string]}>()
const conditional=computed(()=>props.waves.some(w=>w.release_mode==='shared_corridor'))
const firstAttention=computed(()=>props.waves.find(w=>['waiting','blocked','pending'].includes(w.state))?.wave)
const labels:Record<string,string>={waiting:'等待条件',pending:'尚未放行',blocked:'需要复核',executing:'撤离中',completed:'已到集合点',stopped:'已交还控制'}
const clock=(seconds:number)=>`${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(Math.floor(seconds%60)).padStart(2,'0')}`
</script>

<template>
  <section class="release-wave-list" aria-label="楼栋放行与通道条件">
    <h4>楼栋放行进展</h4>
    <p>{{conditional?'前批行动受理后，按通知、供水、车辆与通道负载持续核对；不必等待前批全员到场。':'逐栋等待前批实际到场，每批再次核对有效喷水。'}}</p>
    <ol class="release-wave-list__waves">
      <li v-for="wave in waves" :key="wave.wave" :data-state="wave.state">
        <header><strong>第 {{wave.wave}} 批 · {{wave.buildings?.map(b=>b.name).join('、')||'本批居民'}}</strong><span>{{labels[wave.state]||wave.state}}</span></header>
        <div class="release-wave-list__progress"><progress :value="wave.arrived" :max="Math.max(1,wave.total)" :aria-label="`第 ${wave.wave} 批到场进度`"/><span>{{wave.arrived}} / {{wave.total}} 人到场</span></div>
        <p>{{wave.reason}}</p>
        <details v-if="wave.release_check" :open="wave.wave===firstAttention">
          <summary>放行检查 {{wave.release_check.checks.filter(c=>c.passed).length}} / {{wave.release_check.checks.length}}<span>{{clock(wave.release_check.at_seconds)}}</span></summary>
          <ul class="release-wave-list__checks">
            <li v-for="check in wave.release_check.checks" :key="check.kind" :data-passed="check.passed">
              <AppIcon :name="check.passed?'check':'clock'" :size="18"/>
              <div><strong>{{check.label}} · {{check.passed?'已满足':'未满足'}}</strong><p>{{check.detail}}</p></div>
              <button v-if="check.edge_id" type="button" :disabled="historical" :aria-label="`定位关联通道：${check.label}`" @click="emit('passage',check.edge_id)"><AppIcon name="target" :size="18"/>定位</button>
              <button v-else-if="check.resident_id&&!check.passed" type="button" :disabled="historical" @click="emit('resident',check.resident_id)">查看住户</button>
            </li>
          </ul>
        </details>
        <nav aria-label="本批现场位置"><button v-for="home in wave.buildings??[]" :key="home.id" type="button" :disabled="historical" @click="emit('building',home.id)">定位 {{home.name}}</button><button v-if="wave.resident_id" type="button" @click="emit('resident',wave.resident_id)">查看本批人员</button></nav>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.release-wave-list{margin-block:24px;font-size:16px;line-height:1.65;min-width:0;scroll-margin-top:60px}
.release-wave-list h4{font-size:18px;margin:0 0 8px}
.release-wave-list p{margin:6px 0 12px;overflow-wrap:anywhere}
.release-wave-list ol,.release-wave-list ul{list-style:none;margin:0;padding:0}
.release-wave-list__waves>li{padding-block:18px;border-bottom:1px solid var(--border-default)}
.release-wave-list header{display:flex;gap:8px;justify-content:space-between;align-items:flex-start;flex-wrap:wrap}
.release-wave-list header>span{font-size:14px;line-height:1.65}
.release-wave-list__progress{display:flex;align-items:center;gap:12px;margin-block:12px;flex-wrap:wrap}
.release-wave-list progress{flex:1 1 100px;height:8px;min-width:0;max-width:100%;accent-color:var(--action-primary)}
.release-wave-list progress::-webkit-progress-bar{background:var(--border-default);border-radius:8px}
.release-wave-list progress::-webkit-progress-value{background:#82cbb3;border-radius:8px}
.release-wave-list__progress>span{font-size:14px;font-variant-numeric:tabular-nums}
.release-wave-list summary{display:flex;align-items:center;justify-content:space-between;gap:8px;min-height:44px;cursor:pointer;font-weight:600;text-decoration:underline;text-underline-offset:4px}
.release-wave-list summary>span{font-size:14px;font-weight:400;font-variant-numeric:tabular-nums}
.release-wave-list__checks>li{display:grid;grid-template-columns:18px minmax(0,1fr) auto;align-items:start;gap:10px;padding-block:12px;border-bottom:1px solid var(--border-default)}
.release-wave-list__checks>li>svg{margin-top:5px;color:#e8bd75}
.release-wave-list__checks>li[data-passed=true]>svg{color:#96d6bc}
.release-wave-list__checks strong{font-size:16px;overflow-wrap:anywhere}
.release-wave-list__checks p{font-size:14px;margin-bottom:0}
.release-wave-list button{font:inherit;font-size:14px;min-height:44px;max-width:100%;display:flex;align-items:center;justify-content:center;gap:6px;padding:8px 10px;color:inherit;background:transparent;border:1px solid var(--border-default);border-radius:8px;cursor:pointer}
.release-wave-list button:disabled{opacity:.5;cursor:default}
.release-wave-list nav{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
.release-wave-list :is(button,summary):focus-visible{outline:2px solid #96d6bc;outline-offset:3px}
@media(max-width:420px){.release-wave-list__checks>li{grid-template-columns:18px minmax(0,1fr)}.release-wave-list__checks button{grid-column:2;justify-self:start}}
</style>
