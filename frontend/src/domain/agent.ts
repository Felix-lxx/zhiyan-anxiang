export interface AgentAssignment { id: string; label: string; exit: 'north' | 'south'; vulnerable: boolean; route_kind?: 'robot'; route_reachable: boolean; route_points: Array<{x:number;y:number;height?:number}> }
export interface AgentRobotSupport {
  target:string; can_apply:boolean; notice:string; duration_seconds:number|null
  target_count?:number
  already_completed?:boolean;reusing_task?:boolean;already_arrived?:boolean
  battery_required:number; battery_available?:number
  route_points:Array<{x:number;y:number;height?:number}>
}
export interface AgentCandidate {
  equivalent_rules?:string[]
  allocation?:{rule:'path'|'risk_capacity'|'containment';description:string;changed_residents:number;same_allocation:boolean;peak_risk:number;bottlenecks:Array<{edge_id:string;name:string;assigned:number;waiting:number;flow_capacity:number;risk_score:number;resident_id:string}>}
  baseline_metrics?:{arrived:number;exposed:number;queue_seconds:number}
  id:string; title:string; can_apply:boolean; reason:string; coverage:string; forecast_at:number; forecast_seconds:number
  assignments:AgentAssignment[]
  robot_support?:AgentRobotSupport|null
  assist_resource?:{capacity:number;busy:number;required:number;waves:number|null}
  geometry_issues?:Array<{edge_id:string;name:string;reason:string}>
  metrics:{ north:number;south:number;unreachable:number;arrived:number;exposed:number;queue_seconds:number;score:number;score_delta:number }
}
export interface AgentStepExecution {
  total:number;arrived:number;blocked:number;queued:number;remaining_details:number
  command_recorded:boolean;idle_seconds:number;stalled:boolean
  attention:Array<{id:string;label:string;location:string;behavior:string;arrived:boolean;blocked:boolean;counted:boolean;queue_seconds:number;smoke_exposure:number;bottleneck:string|null;staff_name:string|null;responsible:string|null;escort_state:string|null}>
  evidence:Array<{id:string;sequence:number;at_seconds:number;message:string}>
}
export interface AgentStep { id:string;label:string;resident_ids:string[];exit?:'north'|'south';action?:string;kind?:'robot.command'|'residents.assign'|'indoor.door.set';depends_on?:string[];completion_rule?:string;command_id:string;status:string;reason:string;progress:number;execution?:AgentStepExecution }
export interface AgentCoordination {
  status:string;at_seconds:number
  lanes:Array<{id:string;label:string;state:string;detail:string}>
  issues:Array<{id:string;resident_id:string;label:string;severity:'danger'|'warning';reason:string}>;issue_count?:number
  bottlenecks:Array<{edge_id:string;name:string;waiting:number;resident_id:string;max_wait_seconds:number}>
  robot:{included:boolean;state:string|null;battery:number|null;reason:string|null;steps_completed:number;steps_total:number}
  next_action:{kind:'review'|'replan'|'rollcall'|'focus'|'robot'|'observe'|'missions'|'indoor';label:string;reason:string;resident_id?:string|null;door_id?:string}
}
export interface AgentCaseTask { id:string;label:string;state:string;responsible_role:string;remaining_seconds:number|null;overdue:boolean;blockers:string[];verification_ready:boolean }
export interface AgentRun {
  drill_status?:string
  task_graph?:{version:number;case_tasks?:AgentCaseTask[];nodes:Array<{id:string;label:string;state:string;depends_on:string[];completion_rule:string}>;human_gate:{label:string;state:string;reason:string}}
  resources?:{version:number;resident_count:number;items:Array<{key:string;name:string;kind:string;state:'owned'|'occupied'|'released';revision:number|null}>}
  outcomes?:AgentOutcome[]
  decision?:{revision:number;candidate_id:string;title:string;approved_at:number;forecast_at:number;forecast_seconds:number;metrics:AgentCandidate['metrics'];allocation:AgentCandidate['allocation'];baseline_metrics:AgentCandidate['baseline_metrics']}|null
  recovery?:{at_seconds:number;retained_arrived:number;remaining:number;active_escorts:number}|null
  updated_at_us?:number
  created_at_us?:number
  approval_guard?:{can_approve:boolean;needs_replan:boolean;age_seconds:number;reason:string}|null
  id:string; goal:string; status:string; reason:string; revision:number;approved_revision:number|null;selected_candidate:string|null
  scope:{resident_ids:string[];building_id:string|null;building_name:string;priority_assist:boolean;robot_broadcast?:boolean;completion:string}
  candidates:AgentCandidate[];steps:AgentStep[];planner:string;planner_notice:string;at_seconds:number
  summary:{total:number;arrived:number;counted:number;assisted:number;exposed:number}
  history:Array<{id:string;kind:string;message:string;at_seconds:number}>
  execution?:{at_seconds:number;event_sequence:number;staff:Array<{id:string;name:string;state:string;resident_id:string|null;responsible:string|null;completed_count:number}>;coordination?:AgentCoordination}
}

export interface AgentOutcome {
  revision:number;status:'pending'|'observed';due_seconds:number;title:string
  forecast_at:number;approved_at:number;population:number
  predicted:{arrived:number;exposed:number;queue_seconds:number}
  result:null|{
    observed_at:number;matched:number;early_ended:boolean;approval_delay_seconds:number
    comparable:boolean;actual:AgentOutcome['predicted'];delta:AgentOutcome['predicted']|null
    interventions:Array<{id:string;sequence:number;at_seconds:number;kind:string;message:string}>
    intervention_count:number;last_event_sequence:number;notice:string
  }
}

export interface AgentLiveState {
  id:string;state_version:string;source_version:string;drill_status:string
  buildings:Array<{id:string;name:string}>;runs:AgentRun[]
}

/** HTTP confirmation wins over delayed socket projections of the same plan. */
export function canApplyAgentRun(incoming:AgentRun, current?:AgentRun):boolean {
  if (!current) return true
  if(incoming.id!==current.id)return (incoming.created_at_us??0)>=(current.created_at_us??0)
  if (incoming.revision!==current.revision) return incoming.revision>current.revision
  if ((incoming.updated_at_us??0)!==(current.updated_at_us??0)) return (incoming.updated_at_us??0)>(current.updated_at_us??0)
  return incoming.at_seconds>=current.at_seconds
}
