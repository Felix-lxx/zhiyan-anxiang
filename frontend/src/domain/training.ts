/** Server-owned training guidance. UI actions navigate; they never imply completion. */
export interface TrainingAction {
  id: string
  label: string
  detail: string
  kind: 'start' | 'resume' | 'finish' | 'plan' | 'task' | 'rollcall' | 'locate' | 'indoor' | 'missions' | 'review' | 'acknowledge'
  target_id: string | null
  severity: 'normal' | 'urgent'
}

export interface TrainingBriefing {
  version: number
  case_title: string
  objective: string
  mode: 'assessment' | 'teaching'
  fire_location: string
  population: number
  priority_people: Array<{ id: string; label: string; floor?: number }>
  responsibilities: Array<{ id: string; title: string; role: string }>
  completion_conditions: string[]
  measures: string[]
}

export interface TrainingJourney {
  version: number
  as_of_seconds: number
  phase: 'prepare' | 'detect' | 'respond' | 'verify' | 'review'
  title: string
  paused: boolean
  briefing: TrainingBriefing
  briefing_origin: 'frozen' | 'legacy_derived'
  summary: string
  actions: TrainingAction[]
  additional_action_count: number
  waiting: TrainingAction[]
  completion: { ready: boolean; blockers: string[] }
  resources: {
    staff_available: number
    staff_total: number
    robot_state: string | null
    vehicles: Array<{ id: string; name: string; state: string }>
  }
}
