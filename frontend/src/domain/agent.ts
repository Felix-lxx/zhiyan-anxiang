export interface AgentAssignment { id: string; label: string; exit: 'north' | 'south'; vulnerable: boolean; route_kind?: 'robot'; route_reachable: boolean; route_points: Array<{x:number;y:number;height?:number}> }
export interface AgentRobotSupport {
  target:string; can_apply:boolean; notice:string; duration_seconds:number|null
  already_completed?:boolean
  battery_required:number; battery_available?:number
  route_points:Array<{x:number;y:number;height?:number}>
}
export interface AgentCandidate {
  id:string; title:string; can_apply:boolean; reason:string; coverage:string; forecast_at:number; forecast_seconds:number
  assignments:AgentAssignment[]
  robot_support?:AgentRobotSupport|null
  geometry_issues?:Array<{edge_id:string;name:string;reason:string}>
  metrics:{ north:number;south:number;unreachable:number;arrived:number;exposed:number;queue_seconds:number;score:number;score_delta:number }
}
export interface AgentStep { id:string;label:string;resident_ids:string[];exit?:'north'|'south';action?:string;kind?:'robot.command';depends_on?:string[];command_id:string;status:string;reason:string;progress:number }
export interface AgentRun {
  id:string; goal:string; status:string; reason:string; revision:number;approved_revision:number|null;selected_candidate:string|null
  scope:{resident_ids:string[];building_id:string|null;building_name:string;priority_assist:boolean;robot_broadcast?:boolean;completion:string}
  candidates:AgentCandidate[];steps:AgentStep[];planner:string;planner_notice:string;at_seconds:number
  summary:{total:number;arrived:number;counted:number;assisted:number;exposed:number}
  history:Array<{id:string;kind:string;message:string;at_seconds:number}>
}
