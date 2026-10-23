<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Resident } from '../domain/drill'
const props=defineProps<{people:Resident[];busy:boolean;running:boolean}>()
const emit=defineEmits<{confirm:[ids:string[]];focus:[id:string]}>()
const selected=ref<string[]>([])
const arrived=computed(()=>props.people.filter(p=>p.status==='evacuated'&&!p.counted))
const missing=computed(()=>props.people.filter(p=>p.status!=='evacuated'))
watch(arrived,()=>{const valid=new Set(arrived.value.map(p=>p.id));selected.value=selected.value.filter(id=>valid.has(id))})
</script>
<template>
  <section class="assembly-rollcall">
    <h3>核对实际到场名单</h3><p>到场 {{people.length-missing.length}} / {{people.length}} 人；{{arrived.length}} 人待核验。请逐人确认身份和状态后勾选。</p>
    <label v-for="person in arrived" :key="person.id"><input v-model="selected" type="checkbox" :value="person.id" :disabled="busy||!running"/><span>{{person.label}}{{person.vulnerable?' · 重点人员':''}}</span><button type="button" @click="emit('focus',person.id)">定位</button></label>
    <button type="button" :disabled="busy||!running||!selected.length" @click="emit('confirm',[...selected])">确认已核验的 {{selected.length}} 人</button>
    <p v-if="!running">继续演练后可提交清点。</p><p v-if="!arrived.length">当前没有已到场且未核验的居民。</p>
    <h4 v-if="missing.length">尚未到场 {{missing.length}} 人</h4><button v-for="person in missing" :key="person.id" type="button" @click="emit('focus',person.id)">{{person.label}} · {{person.behavior||'等待撤离'}} · 定位寻找</button>
  </section>
</template>
<style scoped>
.assembly-rollcall{display:grid;gap:16px;font-size:16px;line-height:1.6;min-width:0}.assembly-rollcall h3,.assembly-rollcall h4,.assembly-rollcall p{margin:0}.assembly-rollcall label{display:flex;align-items:center;gap:12px;padding-block:10px;border-bottom:1px solid var(--border-default)}.assembly-rollcall label span{flex:1;overflow-wrap:anywhere}.assembly-rollcall input{width:22px;height:22px;accent-color:var(--action-focus)}.assembly-rollcall button{min-height:44px;padding:10px 14px;font:inherit;color:inherit;background:var(--surface-raised);border:1px solid var(--border-default);border-radius:8px;white-space:normal}
</style>
