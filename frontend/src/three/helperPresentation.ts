export interface HelperState {
  id:string; staff_id?:string; staff_name?:string; resident_id?:string
  x:number;y:number;height?:number;edge_id?:string|null
  state:string;behavior?:string;responsible?:string;met_at_seconds?:number;purpose?:string;started_at_seconds?:number
  congestion?:number;route_reachable?:boolean
  route_points?:Array<{x:number;y:number;height?:number}>
  motion_trace?:Array<{x:number;y:number;height:number;at_seconds:number}>
}

export const helperIdentity = (helper:HelperState) => helper.staff_id || helper.id

/** One visual status across detailed and fallback staff models. */
export function helperPresentation(helper:HelperState) {
  if(helper.purpose==='household_visit'){
    const labels:Record<string,string>={approaching:'沿通道前往户门',at_door:'已到户门，等待核查',blocked:'到户通道受阻',completed:'到户核查已结束'}
    return {label:labels[helper.state]??'核查执行中',color:helper.state==='blocked'?0xff826c:helper.state==='at_door'?0xe8b966:0x77b7ff}
  }
  const states:Record<string,{label:string;color:number}> = {
    approaching:{label:'沿通道前往会合',color:0x77b7ff},
    escorting:{label:'已会合，同行护送',color:0x79ddcd},
    blocked:{label:'护送通道受阻',color:0xff826c},
    completed:{label:'护送完成，在集合区域待命',color:0xadcbb0},
  }
  const state=states[helper.state] ?? {label:'等待执行回执',color:0xe8b966}
  const waiting=(helper.congestion??0)>55 && helper.state!=='completed' && helper.state!=='blocked'
  return {label:waiting?`${state.label} · 正在排队`:state.label,color:waiting?0xe8b966:state.color}
}

/** Task history is not a population: one physical actor per frozen staff slot. */
export function presentHelpers(history:HelperState[]):HelperState[] {
  const latest = new Map<string,HelperState>()
  for (const helper of history) {
    const id = helperIdentity(helper), previous = latest.get(id)
    if (!previous || helper.state !== 'completed' || previous.state === 'completed' &&
        (helper.started_at_seconds??0)>=(previous.started_at_seconds??0)) latest.set(id, helper)
  }
  return [...latest.values()]
}

/** Never replace an unavailable route with a straight line to a person. */
export function meetingRoute(helper:HelperState):NonNullable<HelperState['route_points']> {
  if (helper.state !== 'approaching' || helper.route_reachable === false || (helper.route_points?.length ?? 0) < 2) return []
  return helper.route_points!.filter((point,index,points) => index===0 ||
    Math.hypot(point.x-points[index-1]!.x,point.y-points[index-1]!.y,(point.height??0)-(points[index-1]!.height??0)) > .001)
}
