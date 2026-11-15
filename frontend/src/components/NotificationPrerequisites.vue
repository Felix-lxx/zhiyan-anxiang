<script setup lang="ts">
import type {AgentNotifications} from '../domain/agent'
import AppIcon from './AppIcon.vue'
defineProps<{summary:AgentNotifications;historical?:boolean;stopped?:boolean}>()
const emit=defineEmits<{household:[id:string]}>()
</script>
<template>
  <section class="notice-prerequisites" aria-label="计划中的住户通知条件">
    <header><h4>住户通知条件</h4><span>已确认 {{summary.completed}} / {{summary.total}} 户</span></header>
    <p v-if="stopped">自动下令已停止。这里保留住户通知事实，补充回执不会恢复本计划。</p>
    <p v-else-if="summary.waiting">{{summary.waiting}} 户仍待核实。已满足条件的部分可继续；这些住户取得收到回执后，系统再核对通道和资源。</p>
    <p v-else>本计划的通知条件已满足，人员行动仍以命令回执和实际到场为准。</p>
    <ul><li v-for="house in summary.items" :key="house.id"><div><strong>{{house.label}}</strong><span>{{house.notification_state==='sent'?'已发出 · 等待收到回执':'尚未确认收到'}}</span></div><button type="button" :disabled="historical" @click="emit('household',house.id)"><AppIcon name="phone" :size="18"/>核实这户</button></li></ul>
    <p v-if="summary.waiting>summary.items.length" class="notice-prerequisites__more">其余 {{summary.waiting-summary.items.length}} 户可在住户列表继续核实。</p>
  </section>
</template>
<style scoped>
.notice-prerequisites{margin-block:24px;min-width:0;font-size:16px;line-height:1.65}
.notice-prerequisites header{display:flex;justify-content:space-between;align-items:baseline;gap:8px;flex-wrap:wrap}
.notice-prerequisites h4{margin:0;font-size:18px}.notice-prerequisites header>span{font-size:14px;font-variant-numeric:tabular-nums}
.notice-prerequisites p{margin:10px 0;overflow-wrap:anywhere}.notice-prerequisites ul{padding:0;margin:0;list-style:none}
.notice-prerequisites li{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding-block:14px;border-bottom:1px solid var(--border-default)}
.notice-prerequisites li>div{flex:1 1 170px;min-width:0;overflow-wrap:anywhere}.notice-prerequisites li span{display:block;font-size:14px}
.notice-prerequisites button{font:inherit;display:flex;align-items:center;gap:6px;min-height:44px;padding:8px 12px;border:1px solid var(--border-default);border-radius:8px;color:var(--text-primary);background:var(--surface-panel);cursor:pointer;max-width:100%}
.notice-prerequisites button:disabled{opacity:.5;cursor:default}.notice-prerequisites button:focus-visible{outline:2px solid #a4ddc6;outline-offset:3px}.notice-prerequisites__more{font-size:14px}
</style>
