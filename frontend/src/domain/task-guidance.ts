import type { ExerciseTask } from './task'
import type { KnowledgeResult } from './knowledge'

export interface TaskGuidanceSnapshot {
  drill_id:string;task_id:string;observed_at_seconds:number;event_sequence:number;drill_status:string
  task:Pick<ExerciseTask,'id'|'title'|'kind'|'target'|'status'|'responsible_role'|'assignee'|'assignee_id'|'verification_ready'|'can_submit'|'operation'>
  next_action:{kind:string;label:string};can_submit:boolean;blockers:string[];steps:string[]
  conditions:Array<{id:string;label:string;met:boolean;detail:string}>
  knowledge:KnowledgeResult
}
