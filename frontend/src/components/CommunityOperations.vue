<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import type {CommunityTraining,DutyStaff,HouseholdNotice} from '../domain/community'
import AppIcon from './AppIcon.vue'

const props=defineProps<{community:CommunityTraining;staff?:DutyStaff[];running:boolean;busy:boolean;canReport?:boolean;canLocate?:boolean;canVisit?:boolean}>()
const emit=defineEmits<{notice:[payload:HouseholdNotice];locate:[residentId:string];task:[taskId:string]}>()
const tab=ref<'households'|'staff'>('households')
const filter=ref('pending'),search=ref(''),selection=ref(''),page=ref(0)
const channel=ref<HouseholdNotice['channel']>('phone'),evidence=ref('')
const stateLabels={unnotified:'待通知',sent:'已覆盖 · 待确认',confirmed:'已确认收到'}
const channelLabels={broadcast:'入口广播',phone:'电话联系',knock:'敲门核查'}
const filtered=computed(()=>props.community.households.filter(h=>(filter.value==='all'||filter.value==='pending'&&h.notification_state!=='confirmed'||filter.value===h.notification_state)&&(!search.value||`${h.label} ${h.profiles.join(' ')}`.includes(search.value))))
const visible=computed(()=>filtered.value.slice(page.value*6,page.value*6+6))
const selected=computed(()=>props.community.households.find(h=>h.id===selection.value))
const visit=computed(()=>[...(props.community.visits??[])].reverse().find(v=>v.household_id===selection.value))
const visiting=computed(()=>visit.value&&visit.value.state!=='completed')
const knockReady=computed(()=>props.community.version<2||visit.value?.state==='at_door')
const available=computed(()=>props.staff?.filter(s=>s.state==='available').length??0)
const states:Record<string,string>={available:'未执行，接收时核对计划归属',task:'现场任务占用',approaching:'前往会合',accompanying:'护送同行',blocked:'受阻待处理',completed:'已完成',off_duty:'非值守'}
watch([filter,search],()=>{page.value=0})
watch(selection,()=>{evidence.value='';channel.value='phone'})
watch(()=>visit.value?.state,state=>{if(state==='at_door'&&!evidence.value)channel.value='knock'})
function submit(action:HouseholdNotice['action']){
  if(!selected.value||!props.running||props.busy||!props.canReport||evidence.value.trim().length<6)return
  emit('notice',{action,household_id:selected.value.id,channel:channel.value,message:evidence.value.trim()})
}
function dispatchVisit(){
  if(!selected.value||!props.running||props.busy||!props.canVisit)return
  emit('notice',{action:'household_visit',household_id:selected.value.id,channel:'knock',
    message:`安排值守员前往${selected.value.label}，核查通知接收情况`})
}
</script>

<template>
  <section class="community-operations" aria-label="社区分户通知与夜班岗位">
    <header class="community-operations__heading"><AppIcon name="users"/><div><h2>通知到户，责任到人</h2><p>住户通知、到户核查与夜班岗位协同</p></div></header>
    <p class="community-operations__summary">{{community.summary.confirmed}} / {{community.summary.total}} 户已确认收到，{{community.summary.awaiting_confirmation}} 户待核实。</p>
    <nav class="community-operations__tabs" aria-label="社区协同分区">
      <button type="button" :aria-pressed="tab==='households'" @click="tab='households'">分户通知</button>
      <button type="button" :aria-pressed="tab==='staff'" @click="tab='staff'">夜班岗位 {{available}}/{{staff?.length??0}}</button>
    </nav>
    <div v-if="tab==='households'">
      <button v-if="selected" type="button" class="community-operations__back" @click="selection=''">返回住户列表</button><div v-if="!selected" class="community-operations__filters"><label>查找住户<input v-model="search" type="search" placeholder="楼栋、楼层或画像"/></label><label>通知进度<select v-model="filter"><option value="pending">待处理</option><option value="all">全部住户</option><option value="unnotified">待通知</option><option value="sent">待确认</option><option value="confirmed">已确认</option></select></label></div>
      <p v-if="!selected&&!filtered.length" role="status">当前筛选没有待处理住户，可切换“全部住户”。</p>
      <ul v-if="!selected" class="community-operations__households"><li v-for="house in visible" :key="house.id"><button type="button" :aria-pressed="selection===house.id" @click="selection=house.id"><span><strong>{{house.label}}</strong><span>{{house.resident_ids.length}} 人 · {{house.profiles.join(' / ')}}</span></span><span class="community-operations__state" :data-state="house.notification_state">{{stateLabels[house.notification_state]}}</span></button></li></ul>
      <div v-if="!selected&&filtered.length>6" class="community-operations__pages"><button type="button" :disabled="page===0" @click="page--">上一页</button><span>{{page+1}} / {{Math.ceil(filtered.length/6)}}</span><button type="button" :disabled="(page+1)*6>=filtered.length" @click="page++">下一页</button></div>
      <section v-if="selected" class="community-operations__detail" aria-label="选中住户">
        <header><h3>{{selected.label}}</h3><button v-if="canLocate" type="button" @click="emit('locate',selected.resident_ids[0]!)"><AppIcon name="target"/>定位现场</button></header>
        <p>{{stateLabels[selected.notification_state]}}。收到回执后，由总控安排撤离或接应。</p>
        <details class="community-operations__context"><summary>住户情况与回执记录</summary><p>{{selected.arrived}} / {{selected.resident_ids.length}} 人到场；{{selected.priority}} 名需重点接应。</p>
        <p v-if="selected.direct_contact_required">本户有需直接联系的居民，入口广播不能替代电话或敲门确认。</p>
        <p>已记录方式：{{selected.channels.map(c=>channelLabels[c]).join('、')||'尚无通知记录'}}</p>
        <p v-if="selected.evidence" class="community-operations__evidence">最近回执（{{selected.last_report_at}} 秒）：{{selected.evidence}}</p>
        </details>
        <section v-if="visit||selected.notification_state!=='confirmed'" class="community-operations__visit" aria-label="到户核查执行">
          <h3>到户核查</h3>
          <ol class="community-operations__steps" aria-label="核查流程">
            <li :aria-current="visiting&&visit?.state!=='at_door'?'step':undefined">前往户门</li>
            <li :aria-current="visit?.state==='at_door'?'step':undefined">核查回执</li>
            <li :aria-current="selected.notification_state==='confirmed'?'step':undefined">安排接应</li>
          </ol>
          <p v-if="visit" role="status"><strong>{{visit.staff_name}}</strong> · {{visit.behavior}}</p>
          <p v-else>派出值守员沿通道到户。到达后核查是否收到通知；无人回应时保留未确认状态。</p>
          <button v-if="canVisit&&selected.notification_state!=='confirmed'&&!visiting" type="button" :disabled="!running||busy||available===0" @click="dispatchVisit"><AppIcon name="users"/>派出值守员到户</button>
          <button v-if="visiting&&canVisit" type="button" :disabled="!running||busy||evidence.trim().length<6" @click="submit('household_visit_cancel')">{{visit?.state==='at_door'?'结束本次核查':'撤回到户核查'}}</button>
          <small v-if="visiting&&canVisit">结束或撤回需在下方填写原因；在途人员走完当前通道后释放岗位。</small>
        </section>
        <template v-if="canReport&&running&&selected.notification_state!=='confirmed'">
          <label>本次联系渠道<select v-model="channel"><option value="phone">电话联系</option><option value="knock" :disabled="!knockReady">敲门核查{{knockReady?'':'（等待到户）'}}</option><option value="broadcast">入口广播</option></select></label>
          <label>现场回执<textarea v-model="evidence" rows="3" maxlength="240" placeholder="记录联系过程与结果，至少六个字。未联系到请勿确认收到。"/></label>
          <div class="community-operations__actions"><button type="button" :disabled="busy||evidence.trim().length<6||channel==='knock'&&!knockReady" @click="submit('household_notified')">记录已发出通知</button><button type="button" :disabled="busy||evidence.trim().length<6||!selected.channels.includes(channel)||selected.direct_contact_required&&channel==='broadcast'||channel==='knock'&&!knockReady" @click="submit('household_confirmed')">记录收到回执</button></div>
          <small>先记录通知，再核实收到。回执是参演人员报告，不是系统自动定位。</small>
        </template>
      </section>
    </div>
    <div v-else><p>岗位与到户核查、护送、责任任务共用，结束后释放。</p><ul class="community-operations__staff"><li v-for="person in staff" :key="person.id"><strong>{{person.name}}</strong><span>{{person.activity==='household_visit'?(person.state==='at_door'?'已到户门，等待核查':person.state==='blocked'?'到户通道受阻':'到户核查执行中'):states[person.state]??'正在执行'}}<template v-if="person.responsible"> · {{person.responsible}}</template></span><button v-if="person.task_id&&canLocate" type="button" @click="emit('task',person.task_id)">查看占用任务<AppIcon name="arrowRight"/></button><button v-else-if="person.resident_id&&canLocate" type="button" @click="emit('locate',person.resident_id)">定位{{person.activity==='household_visit'?'核查住户':'护送对象'}}<AppIcon name="arrowRight"/></button></li></ul></div>
  </section>
</template>

<style scoped>
.community-operations{min-width:0;margin-block:20px;padding-block:20px;border-block:1px solid var(--border-default);font-size:16px;line-height:1.65;color:inherit}
.community-operations__visit{margin-block:20px;padding-block:16px;border-block:1px solid var(--border-default)}
.community-operations__visit>button{display:flex;align-items:center;gap:8px;margin-block:12px}
.community-operations__visit small{display:block}
.community-operations__context>summary{min-height:44px;display:flex;align-items:center;cursor:pointer;text-decoration:underline;text-underline-offset:4px}
.community-operations__context[open]>summary{margin-bottom:12px}
.community-operations__context>summary:focus-visible{outline:2px solid var(--action-primary);outline-offset:3px}
.community-operations__steps{display:flex;gap:12px;padding:0;margin:0 0 16px;list-style:none;counter-reset:visit-step;flex-wrap:wrap}
.community-operations__steps li{counter-increment:visit-step;flex:1 1 90px;font-size:14px;line-height:1.6;color:inherit;opacity:.72}
.community-operations__steps li::before{content:counter(visit-step);display:inline-grid;place-items:center;inline-size:24px;block-size:24px;margin-right:6px;border:1px solid currentColor;border-radius:50%;font-variant-numeric:tabular-nums}
.community-operations__steps li[aria-current=step]{font-weight:700;opacity:1}
.community-operations__steps li[aria-current=step]::before{background:var(--action-primary);color:#f4fbf8;border-color:var(--action-primary)}
.community-operations :is(h2,h3,p){margin:0 0 12px;overflow-wrap:anywhere}.community-operations h2{font-size:20px;line-height:1.4}.community-operations h3{font-size:18px}.community-operations__heading{display:flex;gap:12px;align-items:flex-start}.community-operations__heading>svg{flex-shrink:0;margin-top:4px}.community-operations__heading p,.community-operations small,.community-operations__note{font-size:14px;line-height:1.65}.community-operations button,.community-operations input,.community-operations select,.community-operations textarea{box-sizing:border-box;max-width:100%;min-width:0;font:inherit;color:inherit}.community-operations button{min-height:44px;padding:8px 12px;border:1px solid var(--border-default);border-radius:8px;background:transparent;cursor:pointer}.community-operations button[aria-pressed=true]{background:var(--action-primary);color:#f4fbf8}.community-operations button:disabled{opacity:.5;cursor:default}.community-operations__tabs,.community-operations__actions{display:flex;gap:8px;flex-wrap:wrap;margin-block:12px}.community-operations__tabs>button,.community-operations__actions>button{flex:1 1 140px}.community-operations__filters{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);gap:12px;margin-bottom:12px}.community-operations label{display:grid;gap:6px;margin-bottom:12px}.community-operations :is(input,select,textarea){width:100%;padding:10px;border:1px solid var(--border-default);border-radius:8px;background:var(--surface-page)}.community-operations textarea{resize:vertical}.community-operations ul{padding:0;margin:0;list-style:none}.community-operations__households li{border-bottom:1px solid var(--border-default)}.community-operations__households button{display:flex;gap:12px;justify-content:space-between;align-items:flex-start;width:100%;padding:14px 8px;border:0;text-align:left;border-radius:0}.community-operations__households button>span:first-child{min-width:0;flex:1}.community-operations__households strong,.community-operations__households span span{display:block}.community-operations__households span span{font-size:14px}.community-operations__state{font-size:14px;max-width:110px;flex-shrink:0}.community-operations__state[data-state=confirmed]{font-weight:700}.community-operations__pages{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-block:12px}.community-operations__back{margin-top:8px}.community-operations__detail{margin-top:12px;padding-top:16px;border-top:1px solid var(--border-default)}.community-operations__detail header{display:flex;gap:8px;align-items:flex-start;justify-content:space-between;flex-wrap:wrap}.community-operations__detail header button{display:flex;gap:6px;align-items:center}.community-operations__evidence{padding:12px;background:var(--surface-page);border-radius:8px}.community-operations__note{margin-top:18px!important}.community-operations__staff li{display:grid;gap:5px;padding:14px 0;border-bottom:1px solid var(--border-default)}.community-operations__staff button{justify-self:start;display:flex;align-items:center;gap:8px}.community-operations button:focus-visible,.community-operations :is(input,select,textarea):focus-visible{outline:2px solid var(--action-primary);outline-offset:3px}@media(max-width:480px){.community-operations__filters{grid-template-columns:1fr}.community-operations__households button{flex-wrap:wrap}.community-operations__state{max-width:none}}
</style>
