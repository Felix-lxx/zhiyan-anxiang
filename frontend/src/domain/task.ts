export type TaskActionKind = 'accept' | 'arrive' | 'report' | 'submit' | 'release'

export interface ExerciseTask {
  id: string; title: string; target: string; status: string; deadline_seconds: number
  staff_id?:string|null;staff_name?:string|null; kind?: string; responsible_role?: string; remaining_seconds?: number; overdue?: boolean
  can_accept?: boolean; acceptance_blockers?: string[]
  action_report_required?:boolean; can_report?:boolean; action_reported_at?:number|null; action_report_evidence?:string|null
  assignee?: string | null; assignee_id?: string | null; assignment_locked?: boolean; blockers?: string[]; can_submit?: boolean; evidence?: string
  target_position?: { x: number; y: number }; steps?: string[]
  target_device_id?: string; target_floor?: number; device_position?: {x:number;y:number;height:number}
  operation?: {mode:'arrival_receipt';duration_seconds:number;elapsed_seconds:number;remaining_seconds:number;phase:'awaiting_arrival'|'working'|'awaiting_evidence'|'verified'}
  verification_ready?: boolean; action_completed_at?: number | null; deadline_at_seconds?: number | null; completed_on_time?: boolean | null
}
