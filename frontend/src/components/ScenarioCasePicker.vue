<script setup lang="ts">
import type { SceneTemplate } from '../domain/models'
defineProps<{templates:SceneTemplate[];modelValue:string}>()
defineEmits<{'update:modelValue':[id:string]}>()
</script>

<template>
  <fieldset class="scenario-cases">
    <legend>选择演练案例</legend>
    <p>先选择已开放案例，再配置起火点、人员与资源。</p>
    <label v-for="item in templates" :key="item.id" :data-selected="modelValue===item.id" :data-available="item.capabilities.can_create">
      <input type="radio" name="scenario-case" :value="item.id" :checked="modelValue===item.id" :disabled="!item.capabilities.can_create" @change="$emit('update:modelValue',item.id)" />
      <span><span class="scenario-cases__title"><strong>{{item.name}}</strong><span>{{item.capabilities.can_create?'可演练':item.capabilities.status==='planned'?'建设中':'暂不可用'}}</span></span><span class="scenario-cases__description">{{item.capabilities.notice}}</span><span v-if="item.capabilities.features.length" class="scenario-cases__features">{{item.capabilities.features.join(' · ')}}</span></span>
    </label>
  </fieldset>
</template>

<style scoped>
.scenario-cases{min-width:0;margin:0;padding:0;border:0;font-size:16px;line-height:1.65}
legend{padding:0;font-weight:600;font-size:20px}.scenario-cases>p{margin:8px 0 16px;color:var(--text-secondary);font-size:16px}
.scenario-cases label{display:grid;grid-template-columns:20px minmax(0,1fr);gap:12px;padding-block:18px;border-top:1px solid var(--border-default);cursor:pointer;min-width:0}
.scenario-cases label[data-available=false]{cursor:default}.scenario-cases input{width:20px;height:20px;min-height:0;padding:0;margin:4px 0 0;accent-color:var(--color-brand-600)}
.scenario-cases__title{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:6px 16px}.scenario-cases strong{font-size:18px;overflow-wrap:anywhere}.scenario-cases__title>span{font-size:14px;color:var(--text-secondary)}
.scenario-cases__description,.scenario-cases__features{display:block;margin-top:6px;overflow-wrap:anywhere}.scenario-cases__features{font-size:14px;color:var(--text-secondary)}
</style>
