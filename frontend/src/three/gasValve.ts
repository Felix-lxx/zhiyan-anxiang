import * as THREE from 'three'

/** Hardware remains around the frozen valve centre; the pipe clears the hood and pan. */
export function createGasValve(counterDepth:number){
  const group=new THREE.Group();group.name='kitchen-gas-valve'
  const brass=new THREE.MeshStandardMaterial({color:0xad945d,metalness:.65,roughness:.42})
  const steel=new THREE.MeshStandardMaterial({color:0x7d8680,metalness:.7,roughness:.36})
  const yellow=new THREE.MeshStandardMaterial({color:0xe6b865,roughness:.55})
  const offset=Math.min(.18,counterDepth*.3),radius=Math.min(.022,counterDepth*.05)
  const pipe=new THREE.Mesh(new THREE.CylinderGeometry(radius,radius,.70,12),brass)
  pipe.name='gas-riser';pipe.position.set(0,-.08,-offset);group.add(pipe)
  const connector=new THREE.CatmullRomCurve3([new THREE.Vector3(0,0,-offset),new THREE.Vector3(0,.025,-offset*.6),new THREE.Vector3(0,0,0)])
  group.add(new THREE.Mesh(new THREE.TubeGeometry(connector,10,radius,8,false),brass))
  const body=new THREE.Mesh(new THREE.CylinderGeometry(.052,.052,.12,6),brass);group.add(body)
  for(const side of [-1,1]){
    const nut=new THREE.Mesh(new THREE.CylinderGeometry(.037,.037,.055,6),steel);nut.position.set(0,side*.09,0);group.add(nut)
  }
  const hub=new THREE.Mesh(new THREE.CylinderGeometry(.025,.025,.045,12),steel);hub.rotation.x=Math.PI/2;hub.position.z=.052;group.add(hub)
  const handle=new THREE.Mesh(new THREE.BoxGeometry(.036,.24,.025),yellow);handle.name='gas-isolation-lever';handle.position.z=.087;handle.castShadow=true;group.add(handle)
  return {group,handle}
}
