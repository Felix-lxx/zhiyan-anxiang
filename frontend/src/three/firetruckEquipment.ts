import * as THREE from 'three'

/** Fittings remain inside the 2.45 x 6.2 m vehicle footprint. */
export function createFiretruckEquipment(roofHeight = 2.3) {
  const group = new THREE.Group(); group.name = 'firetruck-pump-equipment'
  const steel = new THREE.MeshStandardMaterial({color:0xb9c6c9,metalness:.85,roughness:.29})
  const black = new THREE.MeshStandardMaterial({color:0x24302f,roughness:.73})
  const brass = new THREE.MeshStandardMaterial({color:0xc2a357,metalness:.8,roughness:.3})
  const red = new THREE.MeshStandardMaterial({color:0xb52e24,metalness:.3,roughness:.38})
  const panel = new THREE.Mesh(new THREE.BoxGeometry(.035,.72,1.32),black)
  panel.position.set(1.18,.95,1.8); group.add(panel)
  for (const z of [1.4,1.8,2.2]) {
    const coupling = new THREE.Mesh(new THREE.CylinderGeometry(.075,.075,.075,16),brass)
    coupling.rotation.z = Math.PI/2; coupling.position.set(1.18,.83,z); group.add(coupling)
    const ring = new THREE.Mesh(new THREE.TorusGeometry(.082,.013,6,20),steel)
    ring.rotation.y = Math.PI/2; ring.position.set(1.21,.83,z); group.add(ring)
    const valve = new THREE.Mesh(new THREE.TorusGeometry(.05,.009,6,16),red)
    valve.rotation.y=Math.PI/2; valve.position.set(1.215,.64,z); group.add(valve)
  }
  for (const z of [1.5,2.1]) {
    const dial = new THREE.Mesh(new THREE.CylinderGeometry(.073,.073,.02,20),steel)
    dial.rotation.z = Math.PI/2; dial.position.set(1.205,1.14,z); group.add(dial)
    const face = new THREE.Mesh(new THREE.CircleGeometry(.061,20),new THREE.MeshStandardMaterial({color:0xf0ead7,roughness:.6}))
    face.rotation.y = Math.PI/2; face.position.set(1.22,1.14,z); group.add(face)
    const needle = new THREE.Mesh(new THREE.BoxGeometry(.004,.045,.006),red)
    needle.position.set(1.223,1.154,z-.012); needle.rotation.x=-.5; group.add(needle)
  }
  for (const z of [.2,.9]) {
    const roll = new THREE.Mesh(new THREE.CylinderGeometry(.22,.22,.38,20),new THREE.MeshStandardMaterial({color:0xc3ae78,roughness:.92}))
    roll.rotation.z=Math.PI/2; roll.position.set(0,roofHeight+.22,z); group.add(roll)
    for (const side of [-1,1]) {
      const rim=new THREE.Mesh(new THREE.TorusGeometry(.22,.015,6,24),black)
      rim.rotation.y=Math.PI/2; rim.position.set(side*.19,roofHeight+.22,z); group.add(rim)
    }
  }
  const pump = new THREE.Object3D(); pump.name='water-inlet'; pump.position.set(1.218,.83,1.8)
  const turret = new THREE.Group(); turret.name='roof-monitor'; turret.position.set(0,roofHeight+.13,-.6)
  const stem = new THREE.Mesh(new THREE.CylinderGeometry(.08,.1,.22,12),steel); turret.add(stem)
  const barrel = new THREE.Mesh(new THREE.CylinderGeometry(.045,.07,.48,12),red)
  barrel.rotation.x=Math.PI/2; barrel.position.set(0,.13,-.2); turret.add(barrel)
  const muzzle = new THREE.Object3D(); muzzle.name='water-muzzle'; muzzle.position.set(0,.13,-.44); turret.add(muzzle)
  group.add(pump,turret)
  group.traverse(object=>{if(object instanceof THREE.Mesh){object.castShadow=true;object.receiveShadow=true}})
  return {group,pump,turret,muzzle}
}
