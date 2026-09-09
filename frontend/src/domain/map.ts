export type MapObjectType = 'building' | 'road' | 'fire_lane' | 'exit' | 'assembly_point' | 'fire_hydrant' | 'charging_shed' | 'micro_fire_station'

export type RoadEdgeStatus = 'open' | 'restricted' | 'blocked'

export interface MapObject { id: string; object_type: MapObjectType; name: string; geometry: { x: number; y: number }; properties: Record<string, unknown> }

export interface RoadNode { id: string; name: string; x: number; y: number; is_exit: boolean }

export interface RoadEdge { id: string; name: string; start_node_id: string; end_node_id: string; width_meters: number; status: RoadEdgeStatus }

export interface ReachabilityResult { status: 'passed' | 'warning' | 'failed'; summary: string; total_nodes: number; reachable_nodes: number; exit_node_count: number; blocked_edge_count: number; unreachable_node_ids: string[]; issues: string[] }
