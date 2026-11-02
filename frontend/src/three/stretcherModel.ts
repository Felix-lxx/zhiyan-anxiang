import * as THREE from 'three'
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js'
import { createPerson, posePerson } from './actors'
import { VEHICLE_GROUND_Y } from './roadSurface'

/** Fits the server's 0.8 m wide / 4 m long envelope, including walking feet. */
export function createStretcher() {
  const root = new THREE.Group()
  root.name = 'medical-stretcher-team'
  const steel = new THREE.MeshStandardMaterial({ color: 0xaebfc3, metalness: .8, roughness: .3 })
  const fabric = new THREE.MeshStandardMaterial({ color: 0x416f70, roughness: .92 })
  const straps = new THREE.MeshStandardMaterial({ color: 0x314543, roughness: .85 })
  const rubber = new THREE.MeshStandardMaterial({ color: 0x273333, roughness: .95 })
  const sheet = new THREE.MeshStandardMaterial({ color: 0xd3d9cc, roughness: .96 })
  const add = (name: string, geometry: THREE.BufferGeometry, material: THREE.Material, x: number, y: number, z: number, parent: THREE.Object3D = root) => {
    const mesh = new THREE.Mesh(geometry, material)
    mesh.name = name; mesh.position.set(x, y, z); mesh.castShadow = true; mesh.receiveShadow = true
    parent.add(mesh); return mesh
  }
  const box = (name: string, w: number, h: number, d: number, material: THREE.Material, x: number, y: number, z: number, parent: THREE.Object3D = root) =>
    add(name, new RoundedBoxGeometry(w, h, d, 2, Math.min(.02, w / 4, h / 4, d / 4)), material, x, y, z, parent)
  const tube = (name: string, a: THREE.Vector3, b: THREE.Vector3, radius: number, material: THREE.Material) => {
    const mesh = add(name, new THREE.CylinderGeometry(radius, radius, a.distanceTo(b), 8), material, 0, 0, 0)
    mesh.position.copy(a).lerp(b, .5)
    mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.clone().sub(a).normalize())
  }
  box('mattress', .68, .1, 1.94, fabric, 0, .82, 0)
  box('mattress-base', .7, .055, 1.96, steel, 0, .745, 0)
  const wheels: THREE.Mesh[] = []
  for (const side of [-1, 1]) {
    tube('frame-rail', new THREE.Vector3(side * .36, .73, -1.1), new THREE.Vector3(side * .36, .73, 1.1), .023, steel)
    for (const end of [-1, 1]) {
      tube('lifting-handle', new THREE.Vector3(side * .36, .73, end * .95), new THREE.Vector3(side * .235, .96, end * 1.2), .02, steel)
      box('handle-grip', .095, .045, .11, rubber, side * .235, .96, end * 1.2)
      tube('folding-leg', new THREE.Vector3(side * .29, .72, end * .55), new THREE.Vector3(side * .29, .23, -end * .65), .021, steel)
      tube('caster-fork', new THREE.Vector3(side * .29, .35, end * .65), new THREE.Vector3(side * .29, .14, end * .65), .022, steel)
      const wheel = add('stretcher-wheel', new THREE.CylinderGeometry(.13, .13, .07, 12), rubber, side * .29, .13 - VEHICLE_GROUND_Y, end * .65)
      wheel.rotation.z = Math.PI / 2
      wheel.userData.rest = wheel.quaternion.clone(); wheel.userData.roll = 0; wheels.push(wheel)
    }
    tube('raised-side-rail', new THREE.Vector3(side * .34, .96, -.55), new THREE.Vector3(side * .34, .96, .55), .018, steel)
    for (const end of [-1, 1]) tube('rail-upright', new THREE.Vector3(side * .34, .77, end * .55), new THREE.Vector3(side * .34, .96, end * .55), .018, steel)
  }
  const patient = new THREE.Group(); patient.name = 'stretcher-patient'; root.add(patient)
  box('pillow', .36, .07, .28, sheet, 0, .9, -.72, patient)
  box('patient-blanket', .49, .21, 1.22, sheet, 0, .98, .12, patient)
  const head = add('patient-head', new THREE.SphereGeometry(.14, 12, 10), new THREE.MeshStandardMaterial({ color: 0xd8ad8e, roughness: .85 }), 0, 1.03, -.7, patient)
  head.scale.set(.85, .85, 1.08)
  for (const z of [-.18, .48]) {
    box('restraint-strap', .6, .018, .055, straps, 0, 1.095, z, patient)
    box('strap-buckle', .055, .025, .065, steel, .06, 1.11, z, patient)
  }
  const helpers = [-1, 1].map((end, index) => {
    const helper = createPerson(`stretcher-helper-${index}`, false, true)
    helper.position.set(0, -VEHICLE_GROUND_Y, end * 1.45)
    helper.userData.stretcherEnd = end
    helper.userData.ring.visible = false
    root.add(helper); return helper
  })
  const carriage=new THREE.Group();carriage.name='stretcher-carriage'
  for(const child of [...root.children])if(!helpers.includes(child as THREE.Group))carriage.add(child)
  root.add(carriage);root.userData.carriage=carriage
  root.userData.patient = patient; root.userData.helpers = helpers; root.userData.wheels = wheels
  return root
}

export function poseStretcher(root: THREE.Group, distance: number, seconds: number, effects: boolean) {
  const fold=THREE.MathUtils.clamp((root.userData.boarding??0)*2,0,1)
  root.userData.carriage.traverse((part:THREE.Object3D)=>{
    if(part.name==='folding-leg'||part.name==='caster-fork')part.scale.y=1-fold*.7
  })
  for (const helper of root.userData.helpers as THREE.Group[]) {
    posePerson(helper, distance > .001 && effects, seconds, false, false)
    // Keep arms on the confirmed carrying task instead of swinging through the patient.
    const limbs = helper.userData.limbs as THREE.Group[]
    for (const index of [0, 2]) limbs[index]!.rotation.x = helper.userData.stretcherEnd * .5
  }
  for (const wheel of root.userData.wheels as THREE.Mesh[]) {
    wheel.position.y=.13-VEHICLE_GROUND_Y+fold*.42
    wheel.userData.roll = (wheel.userData.roll - distance / .13) % (Math.PI * 2)
    wheel.quaternion.copy(wheel.userData.rest)
    wheel.quaternion.premultiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), wheel.userData.roll))
  }
}
