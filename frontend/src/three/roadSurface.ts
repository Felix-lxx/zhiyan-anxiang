/** Display metres shared by pavement, risk projection and vehicle anchoring. */
export const ROAD_SURFACE_Y = .008
export const ROAD_RISK_Y = .022
export const VEHICLE_GROUND_Y = ROAD_SURFACE_Y + .006

export function roadWidth(width:number) { return Math.max(.1,Number.isFinite(width)?width:.1) }
