export interface TrainingHousehold {
  id:string; label:string; building_id:string; building_name:string; floor:number
  resident_ids:string[]; notification_state:'unnotified'|'sent'|'confirmed'
  channels:Array<'broadcast'|'phone'|'knock'>; direct_contact_required:boolean
  arrived:number; priority:number; profiles:string[]; last_report_at:number|null; evidence:string
}
export interface HouseholdVisit {
  id:string;household_id:string;resident_id:string;staff_id:string;staff_name:string
  state:string;behavior:string;purpose:'household_visit';participant_id?:string;cancelling?:boolean
  x:number;y:number;height:number;building_id:string;arrived_at_seconds?:number
  route_reachable:boolean;route_points:Array<{x:number;y:number;height?:number}>
  motion_trace?:Array<{x:number;y:number;height:number;at_seconds:number}>
}
export interface CommunityTraining {
  version:number;source:'simulation';label:string;seed:number;notice:string
  households:TrainingHousehold[]
  visits?:HouseholdVisit[]
  summary:{total:number;confirmed:number;unnotified:number;awaiting_confirmation:number}
}
export interface DutyStaff {id:string;name:string;state:string;resident_id?:string|null;task_id?:string;responsible?:string;activity?:string}
export interface HouseholdNotice {
  action:'household_notified'|'household_confirmed'|'household_visit'|'household_visit_cancel';household_id:string
  channel:'broadcast'|'phone'|'knock';message:string
}
