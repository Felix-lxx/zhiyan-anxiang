import * as THREE from 'three'
import type { VisualRoad } from './roadVisuals'
import { ROAD_SURFACE_Y, roadWidth } from './roadSurface'

type Point = {x:number;y:number}
type Mouth = {edge:VisualRoad;atStart:boolean;direction:Point}
export interface StreetCuts {start:number;end:number}

/** Bevel only shared endpoints. Geometric crossings do not create navigation nodes. */
export function roadJunctions(edges:VisualRoad[]) {
  const nodes=new Map<string,{point:Point;mouths:Mouth[]}>()
  const cuts=new Map<string,StreetCuts>()
  for(const edge of edges){
    const length=Math.hypot(edge.end.x-edge.start.x,edge.end.y-edge.start.y)
    if(length<.001)continue
    cuts.set(edge.id,{start:0,end:0})
    for(const atStart of [true,false]){
      const point=atStart?edge.start:edge.end,other=atStart?edge.end:edge.start
      const key=point.id?`id:${point.id}`:`xy:${point.x.toFixed(5)}:${point.y.toFixed(5)}`
      const node=nodes.get(key)??{point,mouths:[]}
      node.mouths.push({edge,atStart,direction:{x:(other.x-point.x)/length,y:(other.y-point.y)/length}})
      nodes.set(key,node)
    }
  }
  const patches:Point[][]=[]
  for(const {point,mouths} of nodes.values()){
    if(mouths.length<2)continue
    const cap:Point[]=[]
    for(const mouth of mouths){
      const width=roadWidth(mouth.edge.width_meters),d=mouth.direction
      for(const side of [-1,1])cap.push({x:point.x+side*d.y*width/2,y:point.y-side*d.x*width/2})
      let inset=width*.5
      for(const other of mouths){
        if(other===mouth)continue
        const cross=Math.abs(d.x*other.direction.y-d.y*other.direction.x)
        const dot=d.x*other.direction.x+d.y*other.direction.y
        if(cross<.001){if(dot>0)inset=Math.max(inset,width);continue}
        inset=Math.max(inset,(roadWidth(other.edge.width_meters)/2+width/2*Math.abs(dot))/cross+.22)
      }
      cuts.get(mouth.edge.id)![mouth.atStart?'start':'end']=inset
    }
    const hull=convexHull(cap)
    if(hull.length>=3)patches.push(hull)
  }
  return {cuts,patches}
}

function convexHull(points:Point[]){
  const sorted=[...new Map(points.map(p=>[`${p.x}:${p.y}`,p])).values()].sort((a,b)=>a.x-b.x||a.y-b.y)
  const cross=(a:Point,b:Point,c:Point)=>(b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x)
  const half=(values:Point[])=>{const result:Point[]=[];for(const p of values){while(result.length>1&&cross(result[result.length-2]!,result[result.length-1]!,p)<=1e-8)result.pop();result.push(p)}return result}
  return [...half(sorted).slice(0,-1),...half([...sorted].reverse()).slice(0,-1)]
}

/** World-aligned UVs make overlapping, coplanar road surfaces sample identical asphalt. */
export function alignRoadTexture(mesh:THREE.Mesh){
  mesh.updateWorldMatrix(true,false)
  const positions=mesh.geometry.getAttribute('position'),uv=new Float32Array(positions.count*2),point=new THREE.Vector3()
  for(let i=0;i<positions.count;i++){
    point.fromBufferAttribute(positions,i).applyMatrix4(mesh.matrixWorld)
    uv[i*2]=point.x/3;uv[i*2+1]=point.z/3
  }
  mesh.geometry.setAttribute('uv',new THREE.BufferAttribute(uv,2))
}

export function createJunctionPatch(points:Point[],material:THREE.Material){
  const shape=new THREE.Shape(points.map(p=>new THREE.Vector2(p.x-50,50-p.y)))
  const geometry=new THREE.ShapeGeometry(shape);geometry.rotateX(-Math.PI/2)
  const mesh=new THREE.Mesh(geometry,material);mesh.name='road-junction-pavement';mesh.position.y=ROAD_SURFACE_Y
  mesh.receiveShadow=true;alignRoadTexture(mesh);return mesh
}
