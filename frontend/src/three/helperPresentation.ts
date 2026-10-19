export interface HelperState {
  id:string; staff_id?:string; staff_name?:string; resident_id?:string
  x:number;y:number;height?:number;edge_id?:string|null
  state:string;behavior?:string;responsible?:string;met_at_seconds?:number
  congestion?:number;route_reachable?:boolean
  route_points?:Array<{x:number;y:number;height?:number}>
}

export const helperIdentity = (helper:HelperState) => helper.staff_id || helper.id

/** Task history is not a population: one physical actor per frozen staff slot. */
export function presentHelpers(history:HelperState[]):HelperState[] {
  const latest = new Map<string,HelperState>()
  for (const helper of history) {
    const id = helperIdentity(helper), previous = latest.get(id)
    if (!previous || previous.state === 'completed' || helper.state !== 'completed') latest.set(id, helper)
  }
  return [...latest.values()]
}

/** Never replace an unavailable route with a straight line to a person. */
export function meetingRoute(helper:HelperState):NonNullable<HelperState['route_points']> {
  if (helper.state !== 'approaching' || helper.route_reachable === false || (helper.route_points?.length ?? 0) < 2) return []
  return helper.route_points!.filter((point,index,points) => index===0 ||
    Math.hypot(point.x-points[index-1]!.x,point.y-points[index-1]!.y,(point.height??0)-(points[index-1]!.height??0)) > .001)
}
