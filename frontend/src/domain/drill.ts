import type { ExerciseTask } from './task'

export interface DrillEvent { id: string; sequence: number; event_type: string; actor: string; message: string; elapsed_seconds: number; payload?: { x?: number; y?: number; target?: string; road_edge_id?: string; blocked_edge_id?: string; blocked_edge_name?: string; route_points?: Array<{ x: number; y: number }>; route_edge_ids?: string[]; severity?: string; impact?: { congested_before: number; congested_after: number; smoke_exposed_before: number; smoke_exposed_after: number; selected_count: number } } }

export type DrillTask = ExerciseTask

export interface Resident { id: string; label: string; vulnerable: boolean; status: string; x: number; y: number; progress: number; exit?: 'north' | 'south'; behavior?: string; smoke_exposure?: number; congestion?: number; speed_factor?: number; route_points?: Array<{ x: number; y: number; height?: number }>; route_edge_ids?: string[]; route_reachable?: boolean; estimated_seconds?: number; remaining_seconds?: number }

export interface RoadEdge { id: string; name: string; start: { x: number; y: number }; end: { x: number; y: number }; width_meters: number; status: 'open' | 'restricted' | 'blocked'; blocked_by_event: boolean; risk_score: number }

export interface Simulation { fire: { intensity: number; smoke_radius: number; temperature: number }; environment: { south_lane: string; east_hydrant: string; visibility: number; blockages?: Array<{ x: number; y: number; target: string }> }; sensors: { temperature: number; smoke_ppm: number; alarm: boolean }; residents: Resident[]; road_network?: { nodes: Array<{ id: string; name: string; x: number; y: number; is_exit: boolean }>; edges: RoadEdge[] }; summary: { total: number; evacuated: number; moving: number; vulnerable: number; missing: number; smoke_exposed?: number; congested?: number; north_load?: number; south_load?: number } }

export interface RobotTask { id: string; label: string; status: string; progress: number; route_edge_ids: string[]; route_points: Array<{ x: number; y: number }>; planned_duration_seconds: number; starts_at_seconds: number; ends_at_seconds: number }

export interface Robot { name: string; state: string; battery: number; x: number; y: number; current_task: string | null; route: string[]; reason: string; task_queue?: RobotTask[] }

export interface Score { total_score: number; details: Array<{ name: string; score: number; max_score?: number; evidence: string; at_seconds?: number }>; recommendations: string[] }

export interface Participant { role: string; name: string; ready: boolean; connected?: boolean; status?: string; last_action?: string | null; last_message?: string | null; last_seen_seconds?: number | null; action_count?: number }

export interface Drill { branch?: { source_name: string } | null; id: string; name: string; status: string; time_scale: number; elapsed_seconds: number; participants: Participant[]; events: DrillEvent[]; tasks: DrillTask[]; robot: Robot | null; score: Score | null; score_preview: Score; simulation: Simulation; engine_version?: number; director_enabled?: boolean }

export interface BranchPlan { strategy: string; name: string; evacuation_seconds: number | null; vulnerable_rescue_seconds: number | null; smoke_exposed: number; congested: number; unreachable: number; average_resident_route_units: number; projected_score: number }

export interface BranchComparison { at_seconds: number; projection_seconds: number; baseline: BranchPlan; alternative: BranchPlan; robots: { baseline: Robot | null; alternative: Robot | null }; worlds: { baseline: Simulation; alternative: Simulation }; improvement: { evacuation_seconds: number | null; vulnerable_rescue_seconds: number | null; smoke_exposed: number; score: number }; recommendation: string; disclaimer: string }

export type SpatialIntent =
  | { kind: 'road'; edgeId: string }
  | { kind: 'robot'; x: number; y: number; target: string }
  | { kind: 'residents'; residentIds: string[]; exit: 'north' | 'south'; action: 'evacuate' | 'priority_assist' }

export interface SpatialPreview {
  kind: 'road' | 'robot' | 'residents'; can_apply: boolean; title?: string; notice: string
  context?: { x: number; y: number; target: string; road_edge_id?: string }
  route_points?: Array<{ x: number; y: number; height?: number }>; route_edge_ids?: string[]
  route_distance?: number; planned_duration_seconds?: number | null; queue_position?: number; risk_score?: number
  width_meters?: number; affected_residents?: number; affected_robot_tasks?: number
  exit?: 'north' | 'south'; action?: 'evacuate' | 'priority_assist'; residents?: Resident[]
  impact?: { congested_before: number; congested_after: number; smoke_exposed_before: number; smoke_exposed_after: number; forecast_horizon_seconds: number }
  intent: SpatialIntent
}
