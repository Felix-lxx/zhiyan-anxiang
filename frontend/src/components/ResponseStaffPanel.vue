<script setup lang="ts">
import type { ResponseStaff, Participant } from '../domain/drill'
import { computed } from 'vue'
const props = defineProps<{ staff: ResponseStaff[]; participants: Participant[]; busy: boolean; ended: boolean }>()
const emit = defineEmits<{ bind: [staffId: string, participantId: string | null] }>()
const members = computed(() => props.participants.filter(p => p.role === '物业/网格员').flatMap(p => p.members ?? []))
const labels: Record<string, string> = {available: '待命', off_duty: '非值守', approaching: '前往会合', blocked: '通道受阻', escorting: '护送同行'}
</script>
<template>
  <details v-if="staff.length" class="response-staff" aria-label="搜索与护送值守人员">
    <summary><strong>搜索与护送值守</strong><span>{{ staff.filter(s=>s.state==='available').length }} / {{ staff.length }} 可用</span></summary>
    <p>同一人员同时执行一项任务。可将模拟岗位交由本场物业参演者负责，任务完成后再交接。</p>
    <article v-for="person in staff" :key="person.id">
      <div><strong>{{ person.responsible || person.name }}</strong><span>{{ labels[person.state] ?? person.state }}<template v-if="person.resident_id"> · {{ person.resident_id }}</template></span></div>
      <label :for="'staff-'+person.id">岗位责任人<select :id="'staff-'+person.id" :value="person.participant_id ?? ''" :disabled="busy || ended || !['available','off_duty'].includes(person.state)" @change="emit('bind', person.id, ($event.target as HTMLSelectElement).value || null)">
        <option value="">{{ person.name }}（模拟）</option>
        <option v-for="member in members" :key="member.id" :value="member.id" :disabled="staff.some(s=>s.id!==person.id && s.participant_id===member.id)">{{ member.name }} · {{ member.online ? '在线' : '离线' }}</option>
      </select></label>
      <small>已完成 {{ person.completed_count }} 项<template v-if="person.participant_id"> · 已绑定本场身份</template></small>
    </article>
  </details>
</template>
<style scoped>
.response-staff{margin-top:24px;padding-top:20px;border-top:1px solid var(--director-line,#3e6055);font-size:16px}
.response-staff summary{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;min-height:44px;cursor:pointer}.response-staff summary>strong{font-size:18px}.response-staff summary:focus-visible{outline:2px solid #9fdec1;outline-offset:2px}.response-staff p{margin:12px 0;line-height:1.65;color:var(--director-muted,#b9cec3)}
.response-staff article{display:grid;gap:10px;padding:16px 0;border-bottom:1px solid var(--director-line,#3e6055)}.response-staff article>div{display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px}.response-staff span,.response-staff small{font-size:14px;color:var(--director-muted,#b9cec3)}.response-staff label{display:grid;gap:6px;font-size:14px}.response-staff select{width:100%;min-width:0;min-height:44px;padding:8px;font-size:16px;color:var(--director-text,#edf3ec);background:var(--director-surface,#10372b);border:1px solid var(--director-line,#3e6055);border-radius:6px}.response-staff select:focus-visible{outline:2px solid #9fdec1;outline-offset:2px}.response-staff select:disabled{opacity:.65}
</style>
