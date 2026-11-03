import * as THREE from 'three'

export interface GasValveVisual {
  group:THREE.Group
  handle:THREE.Mesh<THREE.BoxGeometry,THREE.MeshStandardMaterial>
  setClosed(closed:boolean):void
  step(delta:number,animate:boolean):void
}

/** Hardware remains around the frozen valve centre; the pipe clears the hood and pan. */
export function createGasValve(counterDepth:number):GasValveVisual{
  const group=new THREE.Group();group.name='kitchen-gas-valve'
  const brass=new THREE.MeshStandardMaterial({color:0xad945d,metalness:.65,roughness:.42})
  const steel=new THREE.MeshStandardMaterial({color:0x7d8680,metalness:.7,roughness:.36})
  const yellow=new THREE.MeshStandardMaterial({color:0xe6b865,roughness:.55})
  const offset=Math.min(.18,counterDepth*.3),radius=Math.min(.022,counterDepth*.05)
  const pipe=new THREE.Mesh(new THREE.CylinderGeometry(radius,radius,.70,12),brass)
  pipe.name='gas-riser';pipe.position.set(0,-.08,-offset);group.add(pipe)
  for(const height of [-.28,.17]){
    const clamp=new THREE.Mesh(new THREE.TorusGeometry(radius+.006,.004,6,12),steel)
    clamp.name='gas-pipe-clamp';clamp.rotation.x=Math.PI/2;clamp.position.set(0,height,-offset);group.add(clamp)
    const plate=new THREE.Mesh(new THREE.BoxGeometry(.08,.075,.01),steel)
    plate.name='gas-clamp-wall-plate';plate.position.set(0,height,-offset-.016);group.add(plate)
    for(const side of [-1,1]){
      const screw=new THREE.Mesh(new THREE.CylinderGeometry(.006,.006,.006,6),steel)
      screw.rotation.x=Math.PI/2;screw.position.set(side*.029,height,-offset-.007);group.add(screw)
    }
  }
  const connector=new THREE.CatmullRomCurve3([new THREE.Vector3(0,0,-offset),new THREE.Vector3(0,.025,-offset*.6),new THREE.Vector3(0,0,0)])
  group.add(new THREE.Mesh(new THREE.TubeGeometry(connector,10,radius,8,false),brass))
  const body=new THREE.Mesh(new THREE.CylinderGeometry(.052,.052,.12,6),brass);group.add(body)
  for(const side of [-1,1]){
    const nut=new THREE.Mesh(new THREE.CylinderGeometry(.037,.037,.055,6),steel);nut.position.set(0,side*.09,0);group.add(nut)
  }
  const hub=new THREE.Mesh(new THREE.CylinderGeometry(.025,.025,.045,12),steel);hub.rotation.x=Math.PI/2;hub.position.z=.052;group.add(hub)
  const handle=new THREE.Mesh(new THREE.BoxGeometry(.036,.24,.025),yellow);handle.name='gas-isolation-lever';handle.position.z=.087;handle.castShadow=true;group.add(handle)
  let target=0,initialized=false
  return {group,handle,
    setClosed(closed:boolean){
      target=closed?Math.PI/2:0
      handle.material.color.setHex(closed?0x6dc6ad:0xe6b865)
      group.userData.confirmedState=closed?'closed':'open'
      if(!initialized)handle.rotation.z=target
      initialized=true
    },
    step(delta:number,animate:boolean){
      if(!animate){handle.rotation.z=target;return}
      const change=target-handle.rotation.z
      handle.rotation.z+=Math.sign(change)*Math.min(Math.abs(change),Math.max(0,delta)*Math.PI*1.8)
    }}
}
