import * as THREE from 'three'
import type { SceneMaterials } from './sceneMaterials'
import { batchStaticParts } from './staticMeshBatch'
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js'

export interface KitchenEnvelope {width:number;depth:number;worktopHeight:number;stoveX:number}

/** All solids stay inside the server-validated countertop envelope. */
export function createKitchenAssembly({width:w,depth:d,worktopHeight:top,stoveX}:KitchenEnvelope, materials?:SceneMaterials) {
  const group=new THREE.Group();group.name='detailed-kitchen-assembly'
  const unit=w/4, gap=Math.min(.025,unit*.06), front=d/2
  const paint=new THREE.MeshStandardMaterial({color:0xd8dbd2,roughness:.48})
  const wood=materials?.surface('wood',0xb69b7d,1,2)??new THREE.MeshStandardMaterial({color:0x9d7757,roughness:.7})
  const stone=materials?.surface('stone',0xe4e0d3,2,1)??new THREE.MeshStandardMaterial({color:0xe4e0d3,roughness:.36})
  const steel=new THREE.MeshStandardMaterial({color:0xa6b2b4,metalness:.88,roughness:.25})
  const black=new THREE.MeshStandardMaterial({color:0x19272c,metalness:.28,roughness:.2})
  const gasket=new THREE.MeshStandardMaterial({color:0x35413e,roughness:.8})
  const glass=new THREE.MeshPhysicalMaterial({color:0x18282e,roughness:.18,metalness:.2,clearcoat:1})
  function block(name:string,x:number,y:number,z:number,width:number,height:number,depth:number,material:THREE.Material,radius=.012) {
    const mesh=new THREE.Mesh(new RoundedBoxGeometry(Math.max(.004,width),Math.max(.004,height),Math.max(.004,depth),2,Math.min(radius,width/4,height/4,depth/4)),material)
    mesh.name=name;mesh.position.set(x,y,z);mesh.castShadow=true;mesh.receiveShadow=true;group.add(mesh);return mesh
  }
  function handle(x:number,y:number,length:number) {block('cabinet-handle',x,y,front-.012,length,.014,.024,steel,.005)}
  for(let slot=1;slot<4;slot++) {
    const x=slot===3?stoveX:(slot-1.5)*unit
    if(slot===1){
      // A hollow sink cabinet avoids filling the recessed bowl with a solid body.
      for(const side of [-1,1])block('sink-cabinet-side',x+side*(unit-gap-.02)/2,(top-.05)/2,0,.02,top-.05,d-.02,paint,.004)
      block('sink-cabinet-bottom',x,.13,0,unit-gap,.025,d-.02,paint,.004)
      block('sink-cabinet-back',x,(top-.05)/2,-d/2+.02,unit-gap,top-.05,.02,paint,.004)
    }else block('cabinet-body',x,(top-.05)/2,0,unit-gap,top-.05,d-.02,paint)
    block('recessed-plinth',x,.055,-.015,unit-gap,.11,d-.055,gasket)
    const rows=slot===3?0:slot===2?3:1
    for(let row=0;row<rows;row++){
      const height=(top-.18)/rows-.012,y=.15+height/2+row*(height+.012)
      block(slot===2?'drawer-front':'cabinet-front',x,y,front-.014,unit-gap*2,height,.022,slot===1?wood:paint,.005)
      handle(x,y+height*.27,Math.min(.19,unit*.45))
    }
    if(slot===1){
      // A real hole in the sink worktop, not a dark rectangle laid over a solid slab.
      const holeW=unit*.64,holeD=d*.55,rimW=(unit-gap-holeW)/2,rimD=(d-holeD)/2
      block('sink-rim-left',x-(holeW+rimW)/2,top-.025,0,rimW,.05,d,steel,.004)
      block('sink-rim-right',x+(holeW+rimW)/2,top-.025,0,rimW,.05,d,steel,.004)
      block('sink-rim-back',x,top-.025,-(holeD+rimD)/2,holeW,.05,rimD,steel,.004)
      block('sink-rim-front',x,top-.025,(holeD+rimD)/2,holeW,.05,rimD,steel,.004)
      block('sink-basin',x,top-.15,0,holeW,.025,holeD,steel)
      for(const side of [-1,1])block('sink-bowl-side',x+side*holeW/2,top-.09,0,.018,.13,holeD,steel,.004)
      for(const side of [-1,1])block('sink-bowl-end',x,top-.09,side*holeD/2,holeW,.13,.018,steel,.004)
      const drain=new THREE.Mesh(new THREE.CylinderGeometry(.024,.024,.006,16),black);drain.position.set(x,top-.134,0);group.add(drain)
      const strainer=new THREE.Mesh(new THREE.TorusGeometry(.016,.003,5,16),steel)
      strainer.rotation.x=Math.PI/2;strainer.position.set(x,top-.129,0);strainer.name='sink-strainer';group.add(strainer)
      const curve=new THREE.CatmullRomCurve3([new THREE.Vector3(x,top,-d*.32),new THREE.Vector3(x,top+.22,-d*.32),new THREE.Vector3(x,top+.27,-d*.1),new THREE.Vector3(x,top+.18,-d*.02)])
      const faucet=new THREE.Mesh(new THREE.TubeGeometry(curve,16,.012,8,false),steel);faucet.name='arched-faucet';group.add(faucet)
      block('tap-mixer-base',x,top+.025,-d*.32,.065,.05,.055,steel,.01)
      block('tap-mixer-lever',x+.025,top+.075,-d*.32,.018,.08,.018,steel,.005)
    }else{
      block('stone-worktop',x,top-.025,0,unit-gap,.05,d,stone)
    }
    if(slot===3){
      block('cooktop-glass',x,top+.007,0,unit*.86,.014,d*.85,black,.01)
      for(const side of [-1,1]){
        const burner=new THREE.Mesh(new THREE.TorusGeometry(Math.min(unit*.15,d*.16),.009,6,24),steel)
        burner.rotation.x=Math.PI/2;burner.position.set(x+side*unit*.22,top+.025,0);group.add(burner)
        for(const r of [0,Math.PI/2]){const support=block('burner-support',x+side*unit*.22,top+.035,0,unit*.29,.014,.013,black,.003);support.rotation.y=r}
      }
      block('oven-frame',x,top*.45,front-.025,unit*.83,top*.46,.045,steel)
      block('oven-glass',x,top*.45,front-.005,unit*.7,top*.32,.009,glass,.007)
      handle(x,top*.72,unit*.61)
      for(const side of [-1,1]){
        const knob=new THREE.Mesh(new THREE.CylinderGeometry(.025,.025,.018,12),black)
        knob.rotation.x=Math.PI/2;knob.position.set(x+side*unit*.22,top*.83,front-.012);group.add(knob)
      }
      block('hood',x,1.78,0,unit-gap,.08,d*.9,steel)
      block('hood-chimney',x,1.93,-d*.26,unit*.45,.22,d*.35,steel)
      block('hood-filter',x,1.73,0,unit*.75,.012,d*.66,gasket,.003)
      const vents=new THREE.InstancedMesh(new THREE.BoxGeometry(unit*.68,.006,.007),steel,9)
      const transform=new THREE.Object3D()
      for(let i=0;i<9;i++){transform.position.set(x,1.721,(i-4)*d*.06);transform.updateMatrix();vents.setMatrixAt(i,transform.matrix)}
      group.add(vents)
      const panRadius=Math.min(.14,unit*.2)
      const pan=new THREE.Mesh(new THREE.LatheGeometry([new THREE.Vector2(0,0),new THREE.Vector2(panRadius,0),new THREE.Vector2(panRadius,.07),new THREE.Vector2(panRadius-.008,.07),new THREE.Vector2(panRadius-.008,.008),new THREE.Vector2(0,.008)],24),gasket)
      pan.name='open-cooking-pan';pan.position.set(x-unit*.22,top+.042,0);pan.castShadow=true;group.add(pan)
      block('pan-handle',x-unit*.22+panRadius+.04,top+.095,0,.08,.018,.027,black,.005)
      block('stove-backsplash',x,top+.28,-d/2+.006,unit-gap,.5,.01,materials?.surface('tile',0xd7d9cf,1,2)??paint,.002)
    }
  }
  const fridgeX=-unit*1.5,fridgeH=1.78
  block('fridge-body',fridgeX,fridgeH/2,-.01,unit-gap,fridgeH,d-.02,paint,.025)
  block('fridge-seal',fridgeX,fridgeH/2,front-.026,unit-gap*1.5,fridgeH-.055,.018,gasket)
  for(const [bottom,height] of [[.04,.53],[.59,1.14]]){
    block('fridge-door',fridgeX,bottom+height/2,front-.009,unit-gap*2,height,.018,paint)
    block('fridge-handle',fridgeX+unit*.31,bottom+height*.6,front-.005,.022,Math.min(.25,height*.5),.009,steel,.004)
  }
  for(let slot=2;slot<3;slot++){
    const x=(slot-1.5)*unit
    block('upper-cabinet',x,1.78,-d*.17,unit-gap,.48,d*.55,paint)
    block('upper-door',x,1.78,d*.105,unit-gap*2,.46,.018,slot===1?wood:paint)
    block('under-cabinet-strip',x,1.53,-d*.02,unit*.8,.012,d*.25,new THREE.MeshStandardMaterial({color:0xffe8ba,emissive:0xffd791,emissiveIntensity:1.8}))
  }
  group.userData.envelope={width:w,depth:d,height:2.06}
  batchStaticParts(group,new Set(['cooktop-glass','oven-glass','sink-basin','sink-rim-left','sink-rim-right','sink-rim-front','sink-rim-back']),'kitchen-static-details')
  return group
}
