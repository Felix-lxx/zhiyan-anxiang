import * as THREE from 'three'
import type { Vehicle } from '../domain/drill'
import { ActorMotion } from './actorMotion'

function dispose(root: THREE.Object3D) {
  root.traverse(object => {
    const mesh = object as THREE.Mesh
    mesh.geometry?.dispose()
    if (mesh.material) for (const material of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
      for (const value of Object.values(material)) if (value instanceof THREE.Texture) value.dispose()
      material.dispose()
    }
  })
  root.removeFromParent()
}

/** Presents confirmed vehicle positions. Loading and animation never advance the simulation. */
export class VehicleVisuals {
  readonly layer = new THREE.Group()
  private models = new Map<string, THREE.Group>()
  private motion = new ActorMotion()
  private requests = new Set<AbortController>()
  private disposed = false
  constructor(private register: (object: THREE.Object3D) => void, private dirty: () => void) {}

  update(vehicles: Vehicle[], elapsed: number, running: boolean) {
    const present = new Set(vehicles.map(vehicle => vehicle.id))
    for (const [id, root] of this.models) root.visible = present.has(id)
    for (const vehicle of vehicles) {
      let root = this.models.get(vehicle.id)
      if (!root) {
        root = this.create(vehicle); this.models.set(vehicle.id, root); this.layer.add(root)
        void this.load(root, vehicle)
      }
      root.visible = true
      const detail = `${vehicle.reason}${vehicle.remaining_seconds === null ? '' : ` 剩余 ${vehicle.remaining_seconds} 秒。`}`
      root.traverse(object => { object.userData.selection = { title: vehicle.name, type: '可调度应急车辆', detail, vehicleId: vehicle.id, x: vehicle.x, y: vehicle.y } })
      root.userData.moving = vehicle.state === 'moving'
      root.userData.beacon.visible = running && vehicle.state === 'moving'
      this.motion.accept(root, new THREE.Vector3(vehicle.x - 50, .04, vehicle.y - 50), vehicle.route_points.map(point => new THREE.Vector3(point.x - 50, .04, point.y - 50)), elapsed, running)
    }
  }

  step(delta: number, running: boolean, time: number, effects: boolean) {
    for (const root of this.models.values()) {
      if (!root.visible) continue
      this.motion.step(root, delta, running)
      const beacon = root.userData.beacon as THREE.Mesh
      if (beacon.visible) (beacon.material as THREE.MeshBasicMaterial).opacity = effects ? .55 + Math.sin(time * 8) ** 2 * .45 : .8
    }
  }

  private create(vehicle: Vehicle) {
    const root = new THREE.Group(), body = new THREE.Group()
    root.name = vehicle.id
    const box = (w: number, h: number, d: number, color: number, x: number, y: number, z: number) => {
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), new THREE.MeshStandardMaterial({ color, roughness: .65 }))
      mesh.position.set(x, y, z); mesh.castShadow = true; body.add(mesh)
    }
    const firetruck = vehicle.kind === 'firetruck', length = firetruck ? 6.2 : 5.2
    box(2.1, 1.5, length, firetruck ? 0xb74131 : 0xe8ece3, 0, 1.3, 0)
    box(1.9, .7, 1.3, 0x294d58, 0, 2, -length / 2 + .8)
    box(2.13, .2, length - .2, 0xe9dfb8, 0, 1.25, 0)
    for (const side of [-1, 1]) for (const axle of [-1, 1]) {
      const wheel = new THREE.Mesh(new THREE.CylinderGeometry(.43, .43, .26, 12), new THREE.MeshStandardMaterial({ color: 0x262c30 }))
      wheel.rotation.z = Math.PI / 2; wheel.position.set(side * 1.1, .45, axle * length * .3); body.add(wheel)
    }
    const beacon = new THREE.Mesh(new THREE.BoxGeometry(1.4, .16, .32), new THREE.MeshBasicMaterial({ color: 0x60c8ff, transparent: true }))
    beacon.position.set(0, 2.5, -length / 2 + 1)
    root.add(body, beacon); root.userData.body = body; root.userData.beacon = beacon
    this.register(root)
    return root
  }

  private async load(root: THREE.Group, vehicle: Vehicle) {
    const controller = new AbortController(); this.requests.add(controller)
    const timeout = setTimeout(() => controller.abort(), 15000)
    try {
      const url = `${import.meta.env.BASE_URL}assets/kenney-car-kit/${vehicle.kind}.glb`
      const [{ GLTFLoader }, response] = await Promise.all([import('three/examples/jsm/loaders/GLTFLoader.js'), fetch(url, { signal: controller.signal })])
      if (!response.ok) throw new Error('车辆模型读取失败')
      const { scene } = await new GLTFLoader().parseAsync(await response.arrayBuffer(), url.slice(0, url.lastIndexOf('/') + 1))
      if (this.disposed) { dispose(scene); return }
      const bounds = new THREE.Box3().setFromObject(scene), size = bounds.getSize(new THREE.Vector3()), center = bounds.getCenter(new THREE.Vector3())
      const scale = (vehicle.kind === 'firetruck' ? 6.2 : 5.2) / Math.max(size.x, size.z, .01)
      scene.position.set(-center.x * scale, -bounds.min.y * scale, -center.z * scale); scene.scale.setScalar(scale)
      // Kenney vehicles use their long axis along Z; keep the actor's forward -Z convention.
      scene.traverse(object => {
        object.userData.selection = root.userData.selection
        if ((object as THREE.Mesh).isMesh) { object.castShadow = true; object.receiveShadow = true }
      })
      dispose(root.userData.body); root.add(scene); root.userData.body = scene
      root.userData.beacon.position.y = size.y * scale + .08
      this.dirty()
    } catch { /* The selectable authored vehicle remains available, including its real position. */ }
    finally { clearTimeout(timeout); this.requests.delete(controller) }
  }

  dispose() {
    this.disposed = true
    for (const request of this.requests) request.abort()
    this.motion.clear(); dispose(this.layer); this.models.clear()
  }
}
