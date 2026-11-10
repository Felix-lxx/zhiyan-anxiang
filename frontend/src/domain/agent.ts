export interface AgentAssignment { id: string; label: string; exit: 'north' | 'south'; vulnerable: boolean; route_kind?: 'robot'; route_reachable: boolean; route_points: Array<{x:number;y:number;height?:number}> }
export interface AgentRobotSupport {
  target:string; can_apply:boolean; notice:string; duration_seconds:number|null
  target_count?:number
  already_completed?:boolean;reusing_task?:boolean;already_arrived?:boolean
  battery_required:number; battery_available?:number
  route_points:Array<{x:number;y:number;height?:number}>
}
export interface AgentVehicleSupport {
  water_source?:{id:string;name:string;x:number;y:number}|null
  hose_length?:number
  vehicle_id:string;name:string;can_apply:boolean;notice:string;target_node_id:string|null;target_name:string|null
  duration_seconds:number|null;spray_duration_seconds:number;already_active:boolean
  route_points?:Array<{x:number;y:number;height?:number}>
}
export interface AgentCandidate {
  equivalent_rules?:string[]
  allocation?:{rule:'path'|'risk_capacity'|'containment'|'suppression_staged';description:string;changed_residents:number;same_allocation:boolean;peak_risk:number;bottlenecks:Array<{edge_id:string;name:string;assigned:number;waiting:number;flow_capacity:number;risk_score:number;resident_id:string}>}
  baseline_metrics?:{arrived:number;exposed:number;queue_seconds:number}
  id:string; title:string; can_apply:boolean; reason:string; coverage:string; forecast_at:number; forecast_seconds:number
  assignments:AgentAssignment[]
  robot_support?:AgentRobotSupport|null
  vehicle_support?:AgentVehicleSupport|null
  suppression_notice?:string|null
  release_policy?:{mode:'building_waves'|'immediate';waves:number;requires_active_suppression:boolean;notice:string}
  schedule_assessment?:{kind:'queue_free_schedule';complete:boolean;estimated_completion_at:number|null;notice:string;waves:Array<{wave:number;building_id:string;release_at:number|null;arrival_at:number|null}>;deadline_risks:Array<{task_id:string;title:string;deadline_at:number;estimated_ready_at:number;delay_seconds:number}>}|null
  assist_resource?:{capacity:number;busy:number;required:number;waves:number|null}
  geometry_issues?:Array<{edge_id:string;name:string;reason:string}>
  metrics:{ north:number;south:number;unreachable:number;arrived:number;exposed:number;queue_seconds:number;score:number;score_delta:number;cumulative_exposure?:number;last_arrival_at?:number|null;all_arrived?:boolean }
}
export interface AgentStepExecution {
  total:number;arrived:number;blocked:number;queued:number;remaining_details:number
  command_recorded:boolean;idle_seconds:number;stalled:boolean
  attention:Array<{id:string;label:string;location:string;behavior:string;arrived:boolean;blocked:boolean;counted:boolean;queue_seconds:number;smoke_exposure:number;bottleneck:string|null;staff_name:string|null;responsible:string|null;escort_state:string|null}>
  evidence:Array<{id:string;sequence:number;at_seconds:number;message:string}>
}
export interface AgentStep { id:string;label:string;resident_ids:string[];floor?:number|null;exit?:'north'|'south';action?:string;kind?:'robot.command'|'vehicle.command'|'residents.assign'|'indoor.door.set';arguments?:Record<string,unknown>;depends_on?:string[];completion_rule?:string;command_id:string;status:string;reason:string;progress:number;execution?:AgentStepExecution }
export interface AgentCoordination {
  status:string;at_seconds:number
  lanes:Array<{id:string;label:string;state:string;detail:string}>
  issues:Array<{id:string;resident_id:string;label:string;severity:'danger'|'warning';reason:string}>;issue_count?:number
  bottlenecks:Array<{edge_id:string;name:string;waiting:number;resident_id:string;max_wait_seconds:number}>
  robot:{included:boolean;state:string|null;battery:number|null;reason:string|null;steps_completed:number;steps_total:number}
  vehicle:{included:boolean;state:string|null;reason:string|null;service:string|null;target:string|null;steps_completed:number;steps_total:number}
  release_waves?:Array<{wave:number;total:number;arrived:number;resident_id:string|null;state:string;reason:string;buildings?:Array<{id:string;name:string;total:number;arrived:number}>}>
  case_tasks?:{total:number;completed:number;waiting:number;pending:number;verification_ready:number;overdue:number;next:AgentCaseTask|null}
  next_action:{kind:'review'|'replan'|'rollcall'|'focus'|'robot'|'vehicle'|'observe'|'missions'|'indoor';label:string;reason:string;resident_id?:string|null;door_id?:string;task_id?:string}
}
export interface AgentCaseTask { id:string;kind?:string;label:string;state:string;responsible_role:string;remaining_seconds:number|null;overdue:boolean;completed_on_time?:boolean|null;blockers:string[];verification_ready:boolean;operation_phase?:string|null;depends_on:string[];next_required_action:string;completion_rule:string;automation:'human_verified' }
export interface AgentRun {
  impact?:AgentImpact
  revision_context?:{from_revision:number;baseline:'approved'|'draft';at_seconds:number;impact:AgentImpact;previous_objective:string;previous_forbidden_exits:string[];new_objective?:string;new_forbidden_exits?:string[];candidates:Array<{candidate_id:string;changed_count:number;residents:Array<{resident_id:string;label:string;old_exit:string;new_exit:string;exit_changed:boolean;route_changed:boolean}>}>}|null
  planning?:AgentPlanningReport|null
  knowledge?: import('./knowledge').KnowledgeResult | null
  drill_status?:string
  task_graph?:{version:number;case_tasks?:AgentCaseTask[];nodes:Array<{id:string;label:string;state:string;depends_on:string[];completion_rule:string}>;human_gate:{label:string;state:string;reason:string;depends_on?:string[]}}
  resources?:{version:number;resident_count:number;items:Array<{key:string;name:string;kind:string;state:'owned'|'occupied'|'released';revision:number|null}>}
  outcomes?:AgentOutcome[]
  decision?:{revision:number;candidate_id:string;title:string;approved_at:number;forecast_at:number;forecast_seconds:number;metrics:AgentCandidate['metrics'];allocation:AgentCandidate['allocation'];baseline_metrics:AgentCandidate['baseline_metrics']}|null
  recovery?:{at_seconds:number;retained_arrived:number;remaining:number;active_escorts:number}|null
  updated_at_us?:number
  created_at_us?:number
  approval_guard?:{can_approve:boolean;needs_replan:boolean;age_seconds:number;reason:string}|null
  id:string; goal:string; status:string; reason:string; revision:number;approved_revision:number|null;selected_candidate:string|null
  scope:{resident_ids:string[];building_id:string|null;building_name:string;priority_assist:boolean;robot_broadcast?:boolean;vehicle_suppression?:boolean;completion:string;floors?:number[];objective?:string;forbidden_exits?:string[]}
  candidates:AgentCandidate[];steps:AgentStep[];planner:string;planner_notice:string;at_seconds:number
  summary:{total:number;arrived:number;counted:number;assisted:number;exposed:number}
  history:Array<{id:string;kind:string;message:string;at_seconds:number}>
  execution?:{at_seconds:number;event_sequence:number;staff:Array<{id:string;name:string;state:string;resident_id:string|null;responsible:string|null;completed_count:number}>;coordination?:AgentCoordination}
}
export interface AgentImpact {
  observed_sequence:number;current_sequence:number;at_seconds:number;affected_count:number;step_count:number;robot_affected:boolean
  changes_count:number;events_truncated:boolean
  changes:Array<{id:string;sequence:number;kind:string;at_seconds:number;message:string;location?:string|null;edge_id?:string|null;resident_count:number;robot_affected:boolean}>
  residents:Array<{id:string;label:string;blocked:boolean;location:string;reason:string}>
  steps:Array<{id:string;label:string;kind:string;direct:boolean}>
}
export interface AgentPlanningReport {
  knowledge_assessment?:import('./knowledge').KnowledgeAssessment
  version:number;at_seconds:number;event_sequence:number;objective:string;objective_label:string
  recommended_candidate_id:string|null;mode:'deterministic'|'model_tools';notice:string;explanation?:string;citations?:string[];ranking_method?:string
  checks:Array<{candidate_id:string;valid:boolean;blockers:string[]}>
  trace:Array<{tool:string;label:string;status:'completed'|'rejected';summary:string;round?:number}>
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

export interface BuildingReleaseSignal { id:string;name:string;wave:number;state:string;total:number;arrived:number;reason:string }
/** Display only a matching authoritative projection, never a draft or a past view. */
export function buildingReleaseSignals(feed:AgentLiveState|null,drillId:string,sourceVersion:string|undefined,historical:boolean):BuildingReleaseSignal[]{
  if(historical||!feed||feed.id!==drillId||feed.source_version!==sourceVersion)return []
  const result=new Map<string,BuildingReleaseSignal>()
  const priority:Record<string,number>={blocked:5,stopped:4,waiting:3,executing:2,completed:1}
  for(const run of feed.runs){
    if(!run.approved_revision||!['executing','waiting','needs_review','awaiting_rollcall','completed'].includes(run.status))continue
    for(const wave of run.execution?.coordination?.release_waves??[]){
      for(const building of wave.buildings??[]){
        const existing=result.get(building.id)
        const incoming={...building,wave:wave.wave,state:wave.state,reason:wave.reason}
        if(existing){
          const dominant=(priority[incoming.state]??0)>(priority[existing.state]??0)?incoming:existing
          result.set(building.id,{...dominant,total:existing.total+incoming.total,arrived:existing.arrived+incoming.arrived})
        }else result.set(building.id,incoming)
      }
    }
  }
  return [...result.values()]
}

/** HTTP confirmation wins over delayed socket projections of the same plan. */
export function canApplyAgentRun(incoming:AgentRun, current?:AgentRun):boolean {
  if (!current) return true
  if(incoming.id!==current.id)return (incoming.created_at_us??0)>=(current.created_at_us??0)
  if (incoming.revision!==current.revision) return incoming.revision>current.revision
  if ((incoming.updated_at_us??0)!==(current.updated_at_us??0)) return (incoming.updated_at_us??0)>(current.updated_at_us??0)
  return incoming.at_seconds>=current.at_seconds
}
