import * as THREE from 'three'
import {furnitureFits,type Passage,type FloorRect} from './indoorGeometry'
import type {SceneMaterials} from './sceneMaterials'

/** Compact entrance fit-out; every solid stays outside the reserved walk lane. */
export function createResidentialEntry(zone:FloorRect&{height:number},passages:Passage[],materials:SceneMaterials){
  const group=new THREE.Group();group.name='private-residential-entrance'
  const walls:THREE.Object3D[]=[]
  function box(name:string,w:number,h:number,d:number,x:number,y:number,z:number,material:THREE.Material){
    const mesh=new THREE.Mesh(new THREE.BoxGeometry(w,h,d),material)
    mesh.name=name;mesh.position.set(x,y,z);mesh.castShadow=true;mesh.receiveShadow=true;group.add(mesh);return mesh
  }
  box('entry-floor',zone.width,.018,zone.depth,0,-.009,0,materials.surface('wood',0xac9b7a,zone.width,zone.depth))
  for(const side of [-1,1]){
    const wall={x:zone.x+side*zone.width/2,y:zone.y,width:.08,depth:zone.depth}
    if(furnitureFits(wall,zone.height,passages)){
      walls.push(box('entrance-side-wall',.08,2.45,zone.depth,side*zone.width/2,1.225,0,materials.surface('plaster',0xd7d2bf,1,1)))
      box('entry-skirting',.035,.075,zone.depth,side*(zone.width/2-.05),.04,0,new THREE.MeshStandardMaterial({color:0x766d5e,roughness:.8}))
    }
  }
  const cabinet={x:zone.x-zone.width/2+.17,y:zone.y,width:.25,depth:Math.min(.52,zone.depth-.1)}
  if(furnitureFits(cabinet,zone.height,passages)){
    const finish=materials.surface('wood',0x89704f,1,1)
    box('entry-shoe-cabinet',cabinet.width,.78,cabinet.depth,cabinet.x-zone.x,.39,0,finish)
    box('cabinet-top',cabinet.width+.035,.03,cabinet.depth+.02,cabinet.x-zone.x,.795,0,finish)
    for(const y of [.26,.52])box('cabinet-joint',.006,.008,cabinet.depth-.02,cabinet.x-zone.x+cabinet.width/2+.003,y,0,new THREE.MeshStandardMaterial({color:0x443b2f,roughness:.9}))
  }
  return {group,walls}
}
