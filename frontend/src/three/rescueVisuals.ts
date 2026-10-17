import * as THREE from 'three'
import type { Vehicle } from '../domain/drill'
import { ActorMotion } from './actorMotion'
import { createPerson, posePerson } from './actors'

export interface RescueResident {
  id: string; label: string; x: number; y: number; behavior?: string
  medical_transfer?: { phase: 'pickup' | 'loading' | 'onboard' | 'handing_over' | 'delivered'; vehicle_id: string }
}
const point = (p: { x: number; y: number }, height = .08) => new THREE.Vector3(p.x - 50, height, p.y - 50)

/** Small, reusable scene effects driven exclusively by confirmed rescue actions. */
export class RescueVisuals {
  readonly layer = new THREE.Group()
  private water = new Map<string, { id: string; root: THREE.Group; curve: THREE.QuadraticBezierCurve3; drops: THREE.InstancedMesh }>()
  private stretchers = new Map<string, THREE.Group>()
  private motion = new ActorMotion()
  private transform = new THREE.Object3D()
  constructor(private register: (object: THREE.Object3D) => void) {}

  update(vehicles: Vehicle[], residents: RescueResident[], elapsed: number, running: boolean) {
    for (const item of this.water.values()) item.root.visible = false
    for (const root of this.stretchers.values()) root.visible = false
    for (const vehicle of vehicles) {
      const action = vehicle.service
      if (action?.action === 'spray' && action.target && action.water_source && action.remaining_seconds > 0) {
        let item = this.water.get(vehicle.id)
        if (item?.id !== action.action_id) {
          if (item) this.release(item.root)
          const root = new THREE.Group(), start = point(vehicle, 2.4), end = point(action.target, .4)
          const apex = start.clone().lerp(end, .5); apex.y += Math.min(5, start.distanceTo(end) * .2)
          const curve = new THREE.QuadraticBezierCurve3(start, apex, end)
          const stream = new THREE.Mesh(new THREE.TubeGeometry(curve, 28, .065, 5, false), new THREE.MeshBasicMaterial({ color: 0xbce2ee, transparent: true, opacity: .6, depthWrite: false }))
          const source = point(action.water_source), pump = point(vehicle, .3), bend = source.clone().lerp(pump, .5); bend.y = .14
          const hose = new THREE.Mesh(new THREE.TubeGeometry(new THREE.QuadraticBezierCurve3(source, bend, pump), 16, .09, 6, false), new THREE.MeshStandardMaterial({ color: 0xc9ac65, roughness: .85 }))
          const drops = new THREE.InstancedMesh(new THREE.SphereGeometry(.10, 5, 4), new THREE.MeshBasicMaterial({ color: 0xd5f1fa }), 28)
          drops.frustumCulled = false
          root.add(stream, hose, drops); this.layer.add(root)
          item = { id: action.action_id, root, curve, drops }; this.water.set(vehicle.id, item)
        }
        item.root.visible = true
      }
      if (!action || !['load', 'handover'].includes(action.action)) continue
      const person = residents.find(p => p.id === action.resident_id)
      const routePoints = action.action === 'load' ? action.pickup_points : action.position ? [{ x: vehicle.x, y: vehicle.y }, action.position] : []
      if (!person || !routePoints?.length) continue
      let root = this.stretchers.get(vehicle.id)
      if (!root) { root = this.createStretcher(); this.stretchers.set(vehicle.id, root); this.layer.add(root); this.register(root) }
      root.visible = true
      const approaching = person.medical_transfer?.phase === 'pickup'
      root.userData.patient.visible = !approaching
      let position = point(person), route = routePoints.map(p => point(p))
      if (approaching) {
        route = [...route].reverse()
        const distance = route.slice(1).reduce((sum, p, i) => sum + p.distanceTo(route[i]!), 0)
        let remaining = distance * THREE.MathUtils.clamp((elapsed - action.starts_at_seconds) / Math.max(1, action.approach_seconds ?? 1), 0, 1)
        position = route[route.length - 1]!.clone()
        for (let i = 1; i < route.length; i++) {
          const length = route[i]!.distanceTo(route[i - 1]!)
          if (remaining <= length) { position = route[i - 1]!.clone().lerp(route[i]!, remaining / Math.max(.001, length)); break }
          remaining -= length
        }
      }
      this.motion.accept(root, position, route, elapsed, running)
      root.traverse(object => { object.userData.selection = { title: `${person.label} · 担架接运`, type: '人员接运', detail: person.behavior, residentId: person.id, x: person.x, y: person.y } })
    }
  }

  step(delta: number, running: boolean, seconds: number, effects: boolean) {
    for (const item of this.water.values()) {
      if (!item.root.visible) continue
      for (let i = 0; i < item.drops.count; i++) {
        const t = (i / item.drops.count + (running && effects ? seconds * .7 : 0)) % 1
        this.transform.position.copy(item.curve.getPoint(t)); this.transform.updateMatrix()
        item.drops.setMatrixAt(i, this.transform.matrix)
      }
      item.drops.instanceMatrix.needsUpdate = true
    }
    for (const root of this.stretchers.values()) if (root.visible) {
      const travelled = this.motion.step(root, delta, running)
      for (const helper of root.userData.helpers as THREE.Group[]) posePerson(helper, travelled > .001 && effects, seconds, false, false)
    }
  }

  private createStretcher() {
    const root = new THREE.Group()
    const box = (w: number, h: number, d: number, color: number, x: number, y: number, z: number) => {
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), new THREE.MeshStandardMaterial({ color, roughness: .7 }))
      mesh.position.set(x, y, z); mesh.castShadow = true; root.add(mesh); return mesh
    }
    box(.75, .12, 1.9, 0x416f70, 0, .72, 0)
    for (const side of [-1, 1]) {
      box(.05, .05, 2.5, 0xb4c3c7, side * .43, .65, 0)
      for (const end of [-1, 1]) {
        box(.04, .5, .04, 0xb4c3c7, side * .32, .38, end * .65)
        const wheel = new THREE.Mesh(new THREE.CylinderGeometry(.14, .14, .09, 8), new THREE.MeshStandardMaterial({ color: 0x2c393d }))
        wheel.rotation.z = Math.PI / 2; wheel.position.set(side * .32, .14, end * .65); root.add(wheel)
      }
    }
    const patient = new THREE.Group()
    const blanket = new THREE.Mesh(new THREE.CapsuleGeometry(.25, .95, 4, 8), new THREE.MeshStandardMaterial({ color: 0xb99771, roughness: .9 }))
    blanket.rotation.x = Math.PI / 2; blanket.position.set(0, .98, .1)
    const head = new THREE.Mesh(new THREE.SphereGeometry(.18, 10, 8), new THREE.MeshStandardMaterial({ color: 0xd8ad8e }))
    head.position.set(0, .98, -.7); patient.add(blanket, head); root.add(patient)
    const helpers = [-1, 1].map((side, i) => { const helper = createPerson(`stretcher-helper-${i}`, false, true); helper.position.set(0, 0, side * 1.45); root.add(helper); return helper })
    root.userData.patient = patient; root.userData.helpers = helpers
    return root
  }

  private release(root: THREE.Object3D) {
    root.traverse(object => {
      const mesh = object as THREE.Mesh
      mesh.geometry?.dispose()
      if (mesh.material) for (const material of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) material.dispose()
      if ((object as THREE.InstancedMesh).isInstancedMesh) (object as THREE.InstancedMesh).dispose()
    })
    root.removeFromParent()
  }
  dispose() { this.motion.clear(); this.release(this.layer); this.water.clear(); this.stretchers.clear() }
}
