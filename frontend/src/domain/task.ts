export interface ExerciseTask {
  id: string; title: string; target: string; status: string; deadline_seconds: number
  kind?: string; responsible_role?: string; remaining_seconds?: number; overdue?: boolean
  assignee?: string | null; assignee_id?: string | null; assignment_locked?: boolean; blockers?: string[]; can_submit?: boolean; evidence?: string
  target_position?: { x: number; y: number }; steps?: string[]
}
