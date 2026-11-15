export interface IndoorZone { id:string; name:string; kind:string; floor:number; x:number; y:number; height:number; width:number; depth:number; smoke_density:number; visibility:number; temperature:number }
export interface IndoorDoorOccupant { id:string; kind:'resident'|'helper'; label:string; reason:string }
export interface DoorPortal { x:number; y:number; height:number; width:number; normal_x:number; normal_y:number; clearance_radius:number; wall_depth:number }
export interface IndoorDoor { id:string; label:string; room_id:string; floor:number; kind?:'kitchen'|'apartment_entry';dwelling_id?:string;state:'open'|'closed'; portal?:DoorPortal; can_close?:boolean; blocked_reason?:string|null; occupants?:IndoorDoorOccupant[] }
export interface IndoorDwelling {
  id:string;label:string;floor:number;unit_number:number;apartment_number:string;building_id:string
  kitchen_zone_id:string;entrance_zone_id:string;entrance_node_id:string;door_id:string;kitchen_door_id:string
  household_id?:string|null;notification_state?:'unnotified'|'sent'|'confirmed'|null
  resident_ids:string[];remaining:number;priority:number;entrance_state:'open'|'closed';kitchen_door_state:'open'|'closed';entrance_smoke:number
}
export interface KitchenEquipmentLayout {
  room_id:string
  counter:{x:number;y:number;width:number;depth:number}
  gas_valve?: {id:string;kind:'gas_valve';label:string;room_id:string;floor:number;position:{x:number;y:number;height:number};approach_node_id:string;approach_position:{x:number;y:number;height:number}}
  stove:{id:string;kind:'stove';room_id:string;label:string;floor:number;position:{x:number;y:number;height:number};width:number;depth:number;height:number;ignition_position:{x:number;y:number;height:number};approach_node_id:string;approach_position:{x:number;y:number;height:number}}
}
export interface IndoorPassage {
  id:string;name:string;kind:string;start:{x:number;y:number;height:number};end:{x:number;y:number;height:number}
  width_meters:number;status:string;geometry_blocked?:boolean;density_percent?:number;waiting_count?:number;floors:number[]
}
export interface IndoorFloorReport {
  floor:number;total:number;blocked:number;unconfirmed:number;queued:number;needs_assistance:number
  blocked_resident_ids:string[];critical_passage_id:string|null;reason:string
}
export interface IndoorState { dwellings?:IndoorDwelling[];navigation?:{version:number;passages:IndoorPassage[];floors:IndoorFloorReport[]}; geometry_revision?:number; building_id:string; source_zone_id:string; source_label:string; zones:IndoorZone[]; doors:IndoorDoor[]; equipment_layout_version?:number; equipment_layouts?:KitchenEquipmentLayout[]; equipment_notice?:string; devices?:Array<{id:string;room_id:string;state:'open'|'closed';basis:'initial'|'task_evidence'}> }
