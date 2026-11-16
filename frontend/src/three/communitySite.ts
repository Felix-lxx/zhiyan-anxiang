/** Ground footprints use the same 0–100 coordinates as the frozen community. */
export interface SiteRect { x:number; y:number; width:number; depth:number }
export interface SiteEdge { start:{x:number;y:number}; end:{x:number;y:number}; width_meters:number }
export interface SiteInput {
  objects:Array<SiteRect & {type:string}>
  roads:SiteEdge[]
  passages?:SiteEdge[]
  protectedPoints?:Array<{x:number;y:number;radius:number}>
}
export interface SiteFeature extends SiteRect { kind:'garden'|'bench'|'parking'; id:string }

function validRect(rect:SiteRect) {
  return [rect.x,rect.y,rect.width,rect.depth].every(Number.isFinite) && rect.width>0 && rect.depth>0
}

function segmentTouches(rect:SiteRect, edge:SiteEdge, margin:number) {
  let enter=0, leave=1
  for(const [origin,delta,center,half] of [
    [edge.start.x,edge.end.x-edge.start.x,rect.x,rect.width/2+margin],
    [edge.start.y,edge.end.y-edge.start.y,rect.y,rect.depth/2+margin],
  ] as const) {
    if(Math.abs(delta)<1e-9) { if(origin<center-half || origin>center+half)return false; continue }
    const a=(center-half-origin)/delta, b=(center+half-origin)/delta
    enter=Math.max(enter,Math.min(a,b)); leave=Math.min(leave,Math.max(a,b))
    if(enter>leave)return false
  }
  return true
}

/** Fail closed for malformed geometry. Reservations include the whole solid, not its pivot. */
export class SiteClearance {
  private occupied:SiteRect[]
  private edges:SiteEdge[]
  private valid:boolean
  constructor(input:SiteInput) {
    this.occupied=input.objects.map(o=>({...o}))
    for(const point of input.protectedPoints??[])this.occupied.push({x:point.x,y:point.y,width:point.radius*2,depth:point.radius*2})
    this.edges=[...input.roads,...(input.passages??[])]
    this.valid=this.occupied.every(validRect) && this.edges.every(e=>[
      e.start.x,e.start.y,e.end.x,e.end.y,e.width_meters,
    ].every(Number.isFinite)&&e.width_meters>0)
  }
  fits(rect:SiteRect,margin=.65):boolean {
    if(!this.valid || !validRect(rect) || !Number.isFinite(margin) || margin<0)return false
    if(rect.x-rect.width/2<2 || rect.y-rect.depth/2<2 || rect.x+rect.width/2>98 || rect.y+rect.depth/2>98)return false
    if(this.occupied.some(o=>Math.abs(rect.x-o.x)<(rect.width+o.width)/2+margin && Math.abs(rect.y-o.y)<(rect.depth+o.depth)/2+margin))return false
    return !this.edges.some(e=>segmentTouches(rect,e,e.width_meters/2+margin))
  }
  reserve(rect:SiteRect):boolean {
    if(!this.fits(rect))return false
    this.occupied.push({...rect});return true
  }
}

export function planCommunitySite(input:SiteInput):SiteFeature[] {
  const clearance=new SiteClearance(input), features:SiteFeature[]=[]
  const buildings=input.objects.filter(o=>o.type==='building').slice().sort((a,b)=>a.x-b.x||a.y-b.y)
  function add(kind:SiteFeature['kind'],rect:SiteRect) {
    if(!clearance.reserve(rect))return false
    features.push({...rect,kind,id:`${kind}-${features.length}`});return true
  }
  // Entrance routes, roads, hose access and assembly areas are already reserved.
  for(const building of buildings) {
    for(const side of [-1,1])for(const end of [-1,1]) {
      if(features.filter(f=>f.kind==='garden').length>=10)break
      for(const [width,depth] of [[14,9.5],[10,7.2],[7.5,5.5]] as const) {
        if(add('garden',{x:building.x+side*(building.width/2+width/2+1.25),
          y:building.y+end*(building.depth/2+depth/2+1.25),width,depth}))break
      }
    }
    for(const side of [-1,1]) {
      if(add('bench',{x:building.x+side*(building.width/2+3.1),y:building.y,width:3.8,depth:1.8}))break
    }
  }
  // Fill genuine unused pockets; no visual-only objects are inserted into navigation.
  for(let y=10;y<=90;y+=12)for(let x=10;x<=90;x+=12) {
    if(features.filter(f=>f.kind==='garden').length>=12)break
    if(buildings.some(b=>Math.hypot(x-b.x,y-b.y)<23))add('garden',{x,y,width:9,depth:6.5})
  }
  for(const x of [6,94])for(const y of [15,23,31])add('parking',{x,y,width:2.7,depth:5.6})
  return features
}
