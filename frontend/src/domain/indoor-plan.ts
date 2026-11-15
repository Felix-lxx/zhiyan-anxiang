import type {IndoorZone} from './indoor'

/** A drawing transform only: never displace authoritative room or actor positions. */
export function indoorPlanFrame(zones:IndoorZone[],points:Array<{x:number;y:number}>=[]) {
  if(!zones.length)return null
  const minX=Math.min(...zones.map(z=>z.x-z.width/2),...points.map(p=>p.x)),maxX=Math.max(...zones.map(z=>z.x+z.width/2),...points.map(p=>p.x))
  const minY=Math.min(...zones.map(z=>z.y-z.depth/2),...points.map(p=>p.y)),maxY=Math.max(...zones.map(z=>z.y+z.depth/2),...points.map(p=>p.y))
  const scale=Math.min(424/Math.max(1,maxX-minX),244/Math.max(1,maxY-minY))
  const offsetX=(480-(maxX-minX)*scale)/2,offsetY=(300-(maxY-minY)*scale)/2
  return {scale,point:(x:number,y:number)=>({x:offsetX+(x-minX)*scale,y:offsetY+(y-minY)*scale}),
    rect:(zone:IndoorZone)=>({x:offsetX+(zone.x-zone.width/2-minX)*scale,
      y:offsetY+(zone.y-zone.depth/2-minY)*scale,width:zone.width*scale,height:zone.depth*scale})}
}

export function shortRoomName(zone:IndoorZone) {
  if(zone.id.endsWith(':east')||zone.name.includes('东侧'))return '东侧厨房'
  if(zone.id.endsWith(':west')||zone.name.includes('西侧'))return '西侧厨房'
  return zone.kind==='stairs'?'楼梯':'房间'
}
