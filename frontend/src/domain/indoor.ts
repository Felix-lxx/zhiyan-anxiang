export interface IndoorZone { id:string; name:string; kind:string; floor:number; x:number; y:number; height:number; width:number; depth:number; smoke_density:number; visibility:number; temperature:number }
export interface IndoorDoorOccupant { id:string; kind:'resident'|'helper'; label:string; reason:string }
export interface IndoorDoor { id:string; label:string; room_id:string; floor:number; state:'open'|'closed'; can_close?:boolean; blocked_reason?:string|null; occupants?:IndoorDoorOccupant[] }
export interface KitchenEquipmentLayout {
  room_id:string
  counter:{x:number;y:number;width:number;depth:number}
  gas_valve?: {id:string;kind:'gas_valve';label:string;room_id:string;floor:number;position:{x:number;y:number;height:number};approach_node_id:string;approach_position:{x:number;y:number;height:number}}
  stove:{id:string;kind:'stove';room_id:string;label:string;floor:number;position:{x:number;y:number;height:number};width:number;depth:number;height:number;ignition_position:{x:number;y:number;height:number};approach_node_id:string;approach_position:{x:number;y:number;height:number}}
}
export interface IndoorState { building_id:string; source_zone_id:string; source_label:string; zones:IndoorZone[]; doors:IndoorDoor[]; equipment_layout_version?:number; equipment_layouts?:KitchenEquipmentLayout[]; equipment_notice?:string; devices?:Array<{id:string;room_id:string;state:'open'|'closed';basis:'initial'|'task_evidence'}> }
