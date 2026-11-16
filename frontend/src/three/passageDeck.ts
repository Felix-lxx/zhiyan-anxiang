import * as THREE from 'three'

interface Point {x:number;y:number}
interface Zone extends Point {width:number;depth:number}

function clip(polygon:Point[],axis:'x'|'y',boundary:number,sign:number):Point[] {
  const result:Point[]=[]
  for(let i=0;i<polygon.length;i++) {
    const a=polygon[i]!,b=polygon[(i+1)%polygon.length]!
    const da=(a[axis]-boundary)*sign,db=(b[axis]-boundary)*sign
    if(da>=0)result.push(a)
    if((da>=0)!==(db>=0)) {
      const t=da/(da-db);result.push({x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t})
    }
  }
  return result
}

/** Subtract the finish floors from a route strip, keeping uncovered door thresholds. */
export function uncoveredDeck(start:Point,end:Point,width:number,zones:Zone[]):Point[][] {
  const dx=end.x-start.x,dy=end.y-start.y,length=Math.hypot(dx,dy)
  if(![start.x,start.y,end.x,end.y,width,length].every(Number.isFinite)||length<1e-5||width<=0)return []
  const x=-dy/length*width/2,y=dx/length*width/2
  let polygons:Point[][]=[[{x:start.x+x,y:start.y+y},{x:end.x+x,y:end.y+y},
    {x:end.x-x,y:end.y-y},{x:start.x-x,y:start.y-y}]]
  for(const zone of zones) {
    if(![zone.x,zone.y,zone.width,zone.depth].every(Number.isFinite)||zone.width<=0||zone.depth<=0)continue
    const remaining:Point[][]=[]
    for(const polygon of polygons) {
      let inside=polygon
      for(const [axis,boundary,sign] of [
        ['x',zone.x-zone.width/2,1],['x',zone.x+zone.width/2,-1],
        ['y',zone.y-zone.depth/2,1],['y',zone.y+zone.depth/2,-1],
      ] as const) {
        const outside=clip(inside,axis,boundary,-sign)
        if(outside.length>=3)remaining.push(outside)
        inside=clip(inside,axis,boundary,sign)
        if(inside.length<3)break
      }
    }
    polygons=remaining
  }
  return polygons.filter(p=>Math.abs(p.reduce((area,a,i)=>{
    const b=p[(i+1)%p.length]!;return area+a.x*b.y-b.x*a.y
  },0))>1e-7)
}

export function createPassageDeck(start:THREE.Vector3,end:THREE.Vector3,width:number,zones:Zone[],material:THREE.Material) {
  const group=new THREE.Group();group.name='uncovered-passage-deck'
  for(const polygon of uncoveredDeck({x:start.x,y:start.z},{x:end.x,y:end.z},width,zones)) {
    const shape=new THREE.Shape(polygon.map(p=>new THREE.Vector2(p.x,-p.y)))
    const geometry=new THREE.ExtrudeGeometry(shape,{depth:.12,bevelEnabled:false,steps:1})
    geometry.rotateX(-Math.PI/2)
    const mesh=new THREE.Mesh(geometry,material);mesh.position.y=start.y-.12;mesh.receiveShadow=true;group.add(mesh)
  }
  if(!group.children.length)material.dispose()
  return group
}
