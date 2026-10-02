import * as THREE from 'three'

function part(parent: THREE.Object3D, geometry: THREE.BufferGeometry, material: THREE.Material, x: number, y: number, z: number) {
  const mesh = new THREE.Mesh(geometry, material); mesh.position.set(x,y,z); mesh.castShadow = true; mesh.receiveShadow = true; parent.add(mesh); return mesh
}

/** Articulated residents: dimensions in display metres; identities do not change with risk state. */
export function createPerson(id: string, vulnerable = false, helper = false): THREE.Group {
  const group = new THREE.Group()
  const seed = [...id].reduce((sum,c)=>sum+c.charCodeAt(0),0)
  const shirt = new THREE.MeshStandardMaterial({color:helper?0x366da3:[0x718478,0x93674d,0x576c83,0x857383,0xa9956f][seed%5],roughness:.9})
  const trousers = new THREE.MeshStandardMaterial({color:0x34433e,roughness:.95})
  const skin = new THREE.MeshStandardMaterial({color:[0xc49674,0xdbb38e,0xaf805e][seed%3],roughness:.85})
  const shoes = new THREE.MeshStandardMaterial({color:0x252c29,roughness:.8})
  const torso = new THREE.Group(); torso.position.y=1.04;group.add(torso);group.userData.torso=torso
  const body=part(torso,new THREE.CapsuleGeometry(.2,.3,4,8),shirt,0,.15,0);body.scale.z=.65; group.userData.body=body
  part(torso,new THREE.CylinderGeometry(.065,.075,.13,8),skin,0,.52,0)
  const head=part(torso,new THREE.SphereGeometry(.14,12,10),skin,0,.69,0);head.scale.set(.88,1.15,.92)
  part(torso,new THREE.SphereGeometry(.145,10,8,0,Math.PI*2,0,Math.PI*.45),new THREE.MeshStandardMaterial({color:vulnerable?0xbcbeb4:0x303129,roughness:1}),0,.72,0)
  const limbs: THREE.Group[]=[]
  for(const side of [-1,1]) {
    const arm=new THREE.Group();arm.position.set(side*.235,.37,0);torso.add(arm)
    part(arm,new THREE.CapsuleGeometry(.065,.3,3,6),shirt,0,-.2,0)
    part(arm,new THREE.CapsuleGeometry(.052,.13,3,6),skin,0,-.46,-.03);limbs.push(arm)
    const leg=new THREE.Group();leg.position.set(side*.105,.82,0);group.add(leg)
    part(leg,new THREE.CapsuleGeometry(.078,.58,3,6),trousers,0,-.34,0)
    part(leg,new THREE.BoxGeometry(.16,.095,.28),shoes,0,-.77,-.065);limbs.push(leg)
  }
  if(helper) {
    const reflect=new THREE.MeshStandardMaterial({color:0xe8e3b8,roughness:.65})
    part(torso,new THREE.BoxGeometry(.37,.07,.29),reflect,0,.23,0)
    part(torso,new THREE.SphereGeometry(.16,12,8,0,Math.PI*2,0,Math.PI/2),new THREE.MeshStandardMaterial({color:0xecc758,roughness:.5}),0,.79,0)
  }
  if(vulnerable) {
    const cane=part(torso,new THREE.CylinderGeometry(.018,.023,.92,6),shoes,.32,-.54,-.13)
    cane.rotation.x=-.08
  }
  const ring=part(group,new THREE.RingGeometry(.29,.35,24),new THREE.MeshBasicMaterial({color:helper?0x77b7ff:vulnerable?0xefc66f:0x76c4af,transparent:true,opacity:.6,side:THREE.DoubleSide,depthWrite:false}),0,.025,0)
  ring.rotation.x=-Math.PI/2;group.userData.ring=ring
  group.userData.limbs=limbs;group.userData.phase=seed*.63;group.userData.vulnerable=vulnerable
  const detail=new THREE.Group()
  for(const child of [...group.children])if(child!==ring)detail.add(child)
  const distant=new THREE.Group()
  part(distant,new THREE.CapsuleGeometry(.19,.74,3,6),shirt,0,.94,0).scale.z=.7
  part(distant,new THREE.SphereGeometry(.14,6,5),skin,0,1.73,0)
  part(distant,new THREE.BoxGeometry(.28,.55,.17),trousers,0,.31,0)
  const lod=new THREE.LOD();lod.addLevel(detail,0);lod.addLevel(distant,32,.15);group.add(lod)
  return group
}

export function posePerson(group: THREE.Group, moving: boolean, seconds: number, exposed: boolean, crowded: boolean) {
  const limbs=group.userData.limbs as THREE.Group[] | undefined
  if(!limbs)return
  const swing=moving?Math.sin(seconds*(group.userData.vulnerable?5:7)+group.userData.phase)*(crowded?.16:.42):0
  limbs[0]!.rotation.x=swing;limbs[2]!.rotation.x=-swing
  limbs[1]!.rotation.x=-swing;limbs[3]!.rotation.x=swing
  const torso=group.userData.torso as THREE.Group
  torso.rotation.x=exposed?-.22:group.userData.vulnerable?-.08:0
  if(exposed)limbs[2]!.rotation.x=-1.25
}

export function createPatrolRobot(): THREE.Group {
  const group=new THREE.Group()
  const shell=new THREE.MeshStandardMaterial({color:0xd4d7ce,roughness:.45,metalness:.25})
  const metal=new THREE.MeshStandardMaterial({color:0x34453e,roughness:.45,metalness:.65})
  const rubber=new THREE.MeshStandardMaterial({color:0x202725,roughness:.95})
  part(group,new THREE.BoxGeometry(.88,.26,1.22),metal,0,.35,0)
  part(group,new THREE.CapsuleGeometry(.37,.3,4,12),shell,0,.6,0).scale.set(1,1,1.35)
  const wheels: THREE.Mesh[]=[]
  for(const x of [-.49,.49])for(const z of [-.39,.39]) {
    const wheel=part(group,new THREE.CylinderGeometry(.23,.23,.15,20),rubber,x,.24,z);wheel.rotation.z=Math.PI/2;wheels.push(wheel)
    const hub=part(wheel,new THREE.CylinderGeometry(.12,.12,.16,12),metal,0,0,0);hub.castShadow=false
  }
  part(group,new THREE.CylinderGeometry(.045,.055,.36,10),metal,0,1.02,-.2)
  part(group,new THREE.BoxGeometry(.42,.22,.24),metal,0,1.25,-.2)
  for(const x of [-.12,.12]) {
    const lens=part(group,new THREE.CylinderGeometry(.057,.057,.03,16),new THREE.MeshStandardMaterial({color:0x172f33,emissive:0x24796e,emissiveIntensity:.6,roughness:.16,metalness:.65}),x,1.26,-.335);lens.rotation.x=Math.PI/2
  }
  part(group,new THREE.CylinderGeometry(.17,.17,.08,20),metal,0,1.43,-.14)
  const beacon=part(group,new THREE.CylinderGeometry(.055,.055,.08,12),new THREE.MeshStandardMaterial({color:0xf4c360,emissive:0xff9b24,emissiveIntensity:1.6}),.25,.96,.28)
  for(const x of [-.28,.28])part(group,new THREE.BoxGeometry(.12,.055,.03),new THREE.MeshStandardMaterial({color:0xffefd4,emissive:0xffe2a7,emissiveIntensity:1.8}),x,.58,-.59)
  for(let i=0;i<5;i++)part(group,new THREE.BoxGeometry(.025,.18,.012),metal,(i-2)*.05,.65,.57)
  group.userData.wheels=wheels;group.userData.beacon=beacon
  return group
}
