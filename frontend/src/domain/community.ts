export interface TrainingHousehold {
  id:string; label:string; building_id:string; building_name:string; floor:number
  dwelling_id?:string;unit_number?:number;apartment_number?:string;entrance_node_id?:string;door_id?:string;kitchen_door_id?:string
  resident_ids:string[]; notification_state:'unnotified'|'sent'|'confirmed'
  channels:Array<'broadcast'|'phone'|'knock'>; direct_contact_required:boolean
  arrived:number; priority:number; profiles:string[]; last_report_at:number|null; evidence:string
  priority_remaining?:number;assistance_pending?:number
  members?:Array<{id:string;label:string;traits:string[];profile_label:string;walking_speed?:number;preparation_seconds?:number;needs_assistance:boolean;status:string}>
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
  population?:{version:number;configuration:import('./population').PopulationProfile;configured:boolean;overlap_count:number}
  summary:{total:number;confirmed:number;unnotified:number;awaiting_confirmation:number;direct_contact_pending?:number;assistance_pending?:number}
}
export interface DutyStaff {id:string;name:string;state:string;resident_id?:string|null;task_id?:string;responsible?:string;activity?:string}
export interface HouseholdNotice {
  action:'household_notified'|'household_confirmed'|'household_visit'|'household_visit_cancel';household_id:string
  channel:'broadcast'|'phone'|'knock';message:string
}
