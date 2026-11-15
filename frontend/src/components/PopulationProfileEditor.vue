<script setup lang="ts">
import {computed} from 'vue'
import {defaultPopulationProfile,populationIssue,type PopulationProfile} from '../domain/population'
const props=defineProps<{modelValue:PopulationProfile|null;total:number;disabled?:boolean;overlapCount?:number}>()
const emit=defineEmits<{'update:modelValue':[value:PopulationProfile|null]}>()
const profile=computed(()=>props.modelValue??defaultPopulationProfile(props.total))
const issue=computed(()=>populationIssue(props.modelValue,props.total))
function update(field:keyof PopulationProfile,event:Event){
  emit('update:modelValue',{...profile.value,[field]:(event.target as HTMLInputElement).valueAsNumber})
}
</script>
<template>
  <fieldset id="population-profile" tabindex="-1" class="population-editor" :disabled="disabled" aria-describedby="population-needs-note">
    <legend>按成员需求组织接应</legend>
    <label class="population-editor__toggle"><input type="checkbox" :checked="Boolean(modelValue)" @change="emit('update:modelValue',($event.target as HTMLInputElement).checked?{...profile}:null)"/>自主配置人数与响应条件</label>
    <p id="population-needs-note">行动能力、通知需求和熟睡状态分别配置，同一居民可同时具备多项需求。</p>
    <div class="population-editor__counts">
      <label>需协助行动<input aria-label="需协助行动人数" type="number" :min="0" :max="total" :value="profile.mobility_count" :readonly="!modelValue" @input="update('mobility_count',$event)"/><span>影响接应与护送队列</span></label>
      <label>需直接联系<input aria-label="需直接联系人数" type="number" :min="0" :max="total" :value="profile.direct_contact_count" :readonly="!modelValue" @input="update('direct_contact_count',$event)"/><span>电话或到户核实收到</span></label>
      <label>夜间熟睡<input aria-label="夜间熟睡人数" type="number" :min="0" :max="total" :value="profile.sleeping_count" :readonly="!modelValue" @input="update('sleeping_count',$event)"/><span>增加通知后的准备时间</span></label>
    </div>
    <p v-if="!modelValue">当前按人数与种子分配，修改种子不会改变各项人数。</p>
    <details v-if="modelValue"><summary>步速与响应时间</summary><div class="population-editor__advanced">
      <label>清醒准备时间（秒）<input type="number" min="0" max="120" :value="profile.awake_preparation_seconds" @input="update('awake_preparation_seconds',$event)"/></label>
      <label>熟睡准备时间（秒）<input type="number" min="0" max="180" :value="profile.sleeping_preparation_seconds" @input="update('sleeping_preparation_seconds',$event)"/></label>
      <label>自主行动基础步速（米/秒）<input type="number" min=".8" max="1.8" step=".05" :value="profile.walking_speed" @input="update('walking_speed',$event)"/></label>
      <label>需协助基础步速（米/秒）<input type="number" min=".3" max="1.2" step=".05" :value="profile.mobility_walking_speed" @input="update('mobility_walking_speed',$event)"/></label>
    </div></details>
    <p v-if="issue" class="population-editor__error" role="alert">{{issue}}</p>
    <p v-else-if="overlapCount!==undefined" class="population-editor__result" role="status">本次预览有 {{overlapCount}} 名成员同时具备多项需求；具体住户与岗位将在新场次冻结。</p>
  </fieldset>
</template>
<style scoped>
.population-editor{border:0;border-block:1px solid var(--border-default);padding:20px 0;margin:20px 0;min-width:0;font-size:16px;line-height:1.65}
legend{font-size:18px;font-weight:600;padding:0 8px 0 0}.population-editor p{margin:10px 0;font-size:14px;overflow-wrap:anywhere}
.population-editor .population-editor__toggle{display:flex;align-items:center;justify-content:flex-start;gap:10px;min-height:44px}.population-editor__toggle input{width:18px;height:18px;flex-shrink:0}
.population-editor__counts,.population-editor__advanced{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,150px),1fr));gap:16px;margin-block:16px}
.population-editor__counts{grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.population-editor label:not(.population-editor__toggle){display:flex;flex-direction:column;gap:6px;min-width:0}.population-editor label span{font-size:14px;color:var(--text-secondary)}
.population-editor input:not([type=checkbox]){box-sizing:border-box;width:100%;min-width:0;min-height:44px;padding:8px 12px;font:inherit;color:var(--text-primary);background:var(--surface-input,var(--surface-panel));border:1px solid var(--border-default);border-radius:8px}
input[readonly]{background:var(--surface-raised);color:var(--text-secondary)}input:focus-visible,summary:focus-visible{outline:2px solid var(--action-primary);outline-offset:3px}
summary{cursor:pointer;padding-block:10px;min-height:44px;box-sizing:border-box}.population-editor__error{color:#a53921}.population-editor__result{color:var(--text-secondary)}
</style>
