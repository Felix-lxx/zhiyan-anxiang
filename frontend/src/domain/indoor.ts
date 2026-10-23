export interface IndoorZone { id:string; name:string; kind:string; floor:number; x:number; y:number; height:number; width:number; depth:number; smoke_density:number; visibility:number; temperature:number }
export interface IndoorDoor { id:string; label:string; room_id:string; floor:number; state:'open'|'closed' }
export interface IndoorState { building_id:string; source_zone_id:string; source_label:string; zones:IndoorZone[]; doors:IndoorDoor[] }
