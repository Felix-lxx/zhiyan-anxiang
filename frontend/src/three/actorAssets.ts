import * as THREE from 'three'
import type { GLTF } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { clone as cloneSkeleton } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js'

type PersonRig = {
  model: THREE.Group; mixer: THREE.AnimationMixer; idle: THREE.AnimationAction;
  walk: THREE.AnimationAction; run?: THREE.AnimationAction; action: THREE.AnimationAction; speed: number;
  arm?: THREE.Object3D; armPose?: THREE.Quaternion;
  forearm?: THREE.Object3D; forearmPose?: THREE.Quaternion;
}
type RobotRig = {
  model: THREE.Group; wheels: THREE.Object3D[]; head: THREE.Group; lidar: THREE.Mesh;
  beacon: THREE.Mesh; lamps: THREE.MeshStandardMaterial; heading: number;
  wheelAngles: number[]; batteryBars: THREE.MeshStandardMaterial[];
}
export type ActorAssetStatus = 'loading' | 'ready' | 'fallback'

/** One owner per arena: skeletons are independent, mesh buffers are shared only within
 * that arena. A branch closing must never dispose another world's characters. */
export class ActorAssets {
  private requests = new Map<string, Promise<GLTF>>()
  private people = new Map<THREE.Group, PersonRig>()
  private robots = new Map<THREE.Group, RobotRig>()
  private mounted = new Set<THREE.Object3D>()
  private geometries = new Set<THREE.BufferGeometry>()
  private materials = new Set<THREE.Material>()
  private skeletons = new Set<THREE.Skeleton>()
  private textures = new Set<THREE.Texture>()
  private transfers = new Set<AbortController>()
  private disposed = false
  private pending = 0
  private failed = false
  private retryJobs = new Map<THREE.Group, () => Promise<void>>()
  private attaching = new Set<THREE.Group>()
  private quality: 'high' | 'medium' | 'low' = 'high'

  constructor(private changed: (status: ActorAssetStatus) => void = () => {}) {}

  private track(object: THREE.Object3D) {
    object.traverse(child => {
      const mesh = child as THREE.Mesh
      if (mesh.geometry) this.geometries.add(mesh.geometry)
      for (const material of Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : []) {
        this.materials.add(material)
        for (const value of Object.values(material)) if (value instanceof THREE.Texture) this.textures.add(value)
      }
      if (child instanceof THREE.SkinnedMesh) this.skeletons.add(child.skeleton)
    })
  }

  private load(name: string): Promise<GLTF> {
    const existing = this.requests.get(name)
    if (existing) return existing
    this.pending++; this.changed('loading')
    const controller = new AbortController(); this.transfers.add(controller)
    const timeout = window.setTimeout(() => controller.abort(), 30000)
    const request = import('three/examples/jsm/loaders/GLTFLoader.js')
      .then(async ({ GLTFLoader }) => {
        const response = await fetch(`${import.meta.env.BASE_URL}assets/actors/${name}.glb`, { signal: controller.signal })
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return new GLTFLoader().parseAsync(await response.arrayBuffer(), '')
      })
      .then(asset => {
        this.track(asset.scene)
        if (this.disposed) this.releaseResources()
        return asset
      })
      .catch(error => { this.requests.delete(name); this.failed = true; if (!this.disposed) console.warn(`模型 ${name} 加载失败，保留轻量模型。`, error); throw error })
      .finally(() => { window.clearTimeout(timeout); this.transfers.delete(controller); this.pending--; if (!this.disposed) this.changed(this.pending ? 'loading' : this.failed ? 'fallback' : 'ready') })
    this.requests.set(name, request)
    return request
  }

  async person(root: THREE.Group, id: string, vulnerable = false, helper = false): Promise<void> {
    if (this.disposed || this.people.has(root) || this.attaching.has(root)) return
    this.attaching.add(root)
    root.userData.assetModelStatus = 'loading'
    try {
      const asset = await this.load(helper ? 'helper-worker' : 'resident-casual')
      if (this.disposed || this.people.has(root)) return
      const model = new THREE.Group(); model.name = helper ? 'rigged-helper' : 'rigged-resident'
      const body = cloneSkeleton(asset.scene)
      // Imported bodies face +Z; the simulation uses -Z as forward.
      body.rotation.y = Math.PI
      // SkeletonUtils copies local transforms, not a coherent world-matrix hierarchy.
      // Update ALL bones before measuring skin bounds; mixed bind/world matrices can
      // otherwise produce a 60 m box and shrink an adult down to a few centimetres.
      body.updateMatrixWorld(true)
      body.traverse(child => { if (child instanceof THREE.SkinnedMesh) child.computeBoundingBox() })
      const bounds = new THREE.Box3().setFromObject(body)
      const seed = [...id].reduce((sum, c) => sum + c.charCodeAt(0), 0)
      const height = helper ? 1.78 : vulnerable ? 1.65 : 1.68 + (seed % 5) * .035
      body.scale.multiplyScalar(height / Math.max(.01, bounds.max.y - bounds.min.y))
      body.position.y = -bounds.min.y * body.scale.y
      body.updateMatrixWorld(true)
      const palette = [0x527780, 0x836652, 0x66735d, 0x675d78, 0x8a5145, 0x536681]
      const clonedMaterials = new Map<string, THREE.Material>()
      body.traverse(child => {
        if (!(child instanceof THREE.Mesh)) return
        child.castShadow = true; child.receiveShadow = true
        // Animated bounds change with the pose; using the bind-pose sphere can cull heads/limbs.
        if (child instanceof THREE.SkinnedMesh) child.frustumCulled = false
        const dress = (source: THREE.Material) => {
          const isShirt = child.name.includes('Body') && source.name === 'LightBrown'
          const key = source.uuid + (isShirt ? '-shirt' : '')
          let material = clonedMaterials.get(key)
          if (!material) {
            const fabric = source.clone() as THREE.MeshStandardMaterial
            fabric.metalness = 0; fabric.roughness = .88
            if (!helper && isShirt) fabric.color.setHex(palette[seed % palette.length]!)
            if (vulnerable && source.name === 'Hair') fabric.color.setHex(0xaaa69d)
            material = fabric; clonedMaterials.set(key, material)
          }
          return material
        }
        child.material = Array.isArray(child.material) ? child.material.map(dress) : dress(child.material)
      })
      model.add(body)
      if (helper) {
        // Work kit stays at body scale and remains selectable as part of the helper.
        const pack = new THREE.Mesh(new RoundedBoxGeometry(.31, .36, .15, 2, .025), new THREE.MeshStandardMaterial({ color: 0xb75336, roughness: .86 }))
        pack.position.set(0, 1.08, .19); pack.castShadow = true; model.add(pack)
        const reflective = new THREE.MeshStandardMaterial({ color: 0xe7dfb1, roughness: .55, metalness: .12 })
        for (const x of [-.095, .095]) {
          const strap = new THREE.Mesh(new THREE.BoxGeometry(.035, .4, .015), reflective)
          strap.position.set(x, 1.13, -.12); model.add(strap)
        }
        const band = new THREE.Mesh(new THREE.BoxGeometry(.29, .045, .015), reflective)
        band.position.set(0, 1.06, .272); model.add(band)
      }
      const mixer = new THREE.AnimationMixer(body)
      const idleClip = asset.animations.find(clip => clip.name.endsWith('|Idle_Neutral')) ?? asset.animations.find(clip => clip.name.endsWith('|Idle'))
      const walkClip = asset.animations.find(clip => clip.name.endsWith('|Walk'))
      if (!idleClip || !walkClip) { this.track(model); throw new Error('人物缺少待机或行走动作') }
      const idle = mixer.clipAction(idleClip).play(), walk = mixer.clipAction(walkClip)
      const runClip = asset.animations.find(clip => clip.name.endsWith('|Run'))
      const run = runClip ? mixer.clipAction(runClip) : undefined
      idle.time = (seed % 17) / 17 * idleClip.duration
      mixer.update(0)
      const arm = body.getObjectByName('UpperArmR') ?? body.getObjectByName('UpperArm_R') ?? body.getObjectByName('UpperArm.R')
      const forearm = body.getObjectByName('LowerArmR')
      this.people.set(root, { model, mixer, idle, walk, run, action: idle, speed: 0, arm, forearm })
      this.mountPerson(root, model)
      this.track(model); root.userData.assetModelStatus = 'ready'
      this.changed(this.pending ? 'loading' : this.failed ? 'fallback' : 'ready')
    } catch {
      if (!this.disposed) { root.userData.assetModelStatus = 'fallback'; this.failed = true; this.retryJobs.set(root, () => this.person(root, id, vulnerable, helper)); this.changed('fallback') }
    } finally { this.attaching.delete(root); if (this.people.has(root)) this.retryJobs.delete(root) }
  }

  private mountPerson(root: THREE.Group, model: THREE.Group) {
    const lod = root.children.find(child => child instanceof THREE.LOD) as THREE.LOD | undefined
    if (!lod) return
    // Keep the articulated original for distant views and failed asset requests.
    const fallback = lod.levels[0]!.object
    const distant = lod.levels[1]!.object
    lod.remove(fallback, distant); lod.levels.length = 0
    lod.addLevel(model, 0); lod.addLevel(fallback, this.personDistance(), .12)
    lod.addLevel(distant, this.personDistance() * 2, .12)
    this.mounted.add(model)
    root.userData.actorLod = lod
    // Root is already registered with recursive raycasting: do not add duplicate raycast roots.
    model.traverse(child => { child.userData.selection = root.userData.selection })
  }

  updatePerson(root: THREE.Group, delta: number, distance: number, active: boolean, camera?: THREE.Camera): boolean {
    const rig = this.people.get(root)
    if (!rig) return false
    const lod = root.userData.actorLod as THREE.LOD
    if (camera) lod.update(camera)
    if (!root.visible || !rig.model.visible) return false
    if (rig.arm && rig.armPose) rig.arm.quaternion.copy(rig.armPose)
    if (rig.forearm && rig.forearmPose) rig.forearm.quaternion.copy(rig.forearmPose)
    const measuredSpeed = active && delta > 0 ? Math.min(3, distance / delta) : 0
    rig.speed = active ? THREE.MathUtils.damp(rig.speed, measuredSpeed, 12, delta) : 0
    const moving = measuredSpeed > .025 && rig.speed > .065
    const running = !root.userData.vulnerable && !root.userData.crowded && !root.userData.exposed && rig.speed > (rig.action === rig.run ? 1.45 : 1.75)
    const to = moving ? running && rig.run ? rig.run : rig.walk : rig.idle
    if (to !== rig.action) {
      const from = rig.action
      to.reset().setEffectiveWeight(1).play(); from.crossFadeTo(to, .18, false)
      rig.action = to
    }
    rig.walk.setEffectiveTimeScale(THREE.MathUtils.clamp(rig.speed / .95, .2, 2))
    rig.run?.setEffectiveTimeScale(THREE.MathUtils.clamp(rig.speed / 2.4, .6, 1.4))
    // Simulation pause / reduced motion freezes both idle breathing and locomotion.
    rig.mixer.update(active ? delta : 0)
    rig.model.rotation.x = root.userData.exposed ? -.1 : root.userData.vulnerable ? -.045 : 0
    if (rig.arm) {
      rig.armPose = rig.arm.quaternion.clone()
      if (root.userData.exposed) rig.arm.rotateX(-.65)
      else if (root.userData.behaviorState === 'escorting') { rig.arm.rotateZ(-.18); rig.arm.rotateX(-.25) }
    }
    if (rig.forearm) {
      rig.forearmPose = rig.forearm.quaternion.clone()
      if (root.userData.exposed) rig.forearm.rotateX(-.85)
    }
    return true
  }

  async robot(root: THREE.Group): Promise<void> {
    if (this.disposed || this.robots.has(root) || this.attaching.has(root)) return
    this.attaching.add(root)
    root.userData.assetModelStatus = 'loading'
    try {
      const asset = await this.load('husky-parts')
      if (this.disposed || this.robots.has(root)) return
      const model = new THREE.Group(); model.name = 'inspection-ugv'
      const chassis = new THREE.Group()
      chassis.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(new THREE.Vector3(0, 0, -1), new THREE.Vector3(-1, 0, 0), new THREE.Vector3(0, 1, 0)))
      chassis.position.y = .13228; model.add(chassis)
      const component = (name: string, x = 0, y = 0, z = 0) => {
        const source = asset.scene.getObjectByName(name)
        if (!source) throw new Error(`底盘缺少 ${name}`)
        const instance = source.clone(true); instance.position.set(x, y, z); chassis.add(instance); return instance
      }
      component('base_link'); component('top_chassis'); component('top_plate', .0812, 0, .245)
      component('bumper', .48, 0, .091); component('bumper', -.48, 0, .091).rotation.z = Math.PI
      const wheels: THREE.Object3D[] = []
      for (const x of [-.256, .256]) for (const y of [-.2775, .2775]) {
        const pivot = new THREE.Group(); pivot.position.set(x, y, .03282); chassis.add(pivot)
        const wheel = component('wheel'); chassis.remove(wheel); pivot.add(wheel); wheels.push(pivot)
      }
      const metal = new THREE.MeshStandardMaterial({ color: 0x303b3f, roughness: .48, metalness: .65 })
      const shell = new THREE.MeshStandardMaterial({ color: 0xdadfd9, roughness: .6, metalness: .2 })
      const glass = new THREE.MeshStandardMaterial({ color: 0x122a32, roughness: .18, metalness: .55 })
      const lamps = new THREE.MeshStandardMaterial({ color: 0x91dfc3, emissive: 0x55d5af, emissiveIntensity: .7 })
      const add = (geometry: THREE.BufferGeometry, material: THREE.Material, x: number, y: number, z: number, parent: THREE.Object3D = model) => {
        const mesh = new THREE.Mesh(geometry, material); mesh.position.set(x, y, z); parent.add(mesh); return mesh
      }
      add(new RoundedBoxGeometry(.4, .16, .46, 2, .018), shell, 0, .49, .04)
      for (const x of [-.16, .16]) for (const z of [-.12, .2]) add(new THREE.CylinderGeometry(.012, .012, .012, 8), metal, x, .576, z)
      // Inspection mast, dual cameras, rotating lidar and sealed speaker housing.
      add(new THREE.CylinderGeometry(.026, .034, .38, 12), metal, 0, .73, -.17)
      const head = new THREE.Group(); head.position.set(0, .94, -.17); model.add(head)
      add(new RoundedBoxGeometry(.3, .14, .14, 2, .012), shell, 0, 0, 0, head)
      for (const x of [-.087, .087]) {
        const rim = add(new THREE.CylinderGeometry(.045, .045, .026, 20), metal, x, 0, -.084, head); rim.rotation.x = Math.PI / 2
        const lens = add(new THREE.CylinderGeometry(.033, .033, .028, 20), glass, x, 0, -.092, head); lens.rotation.x = Math.PI / 2
      }
      const lidar = add(new THREE.CylinderGeometry(.095, .095, .075, 24), metal, 0, 1.065, -.17)
      add(new THREE.BoxGeometry(.065, .018, .01), glass, 0, 0, -.094, lidar)
      add(new THREE.CylinderGeometry(.065, .065, .018, 24), shell, 0, 1.11, -.17)
      add(new RoundedBoxGeometry(.17, .15, .12, 2, .008), metal, 0, .655, .17)
      for (let i = 0; i < 5; i++) add(new THREE.BoxGeometry(.125, .009, .006), shell, 0, .611 + i * .021, .234)
      add(new THREE.CylinderGeometry(.007, .012, .31, 8), metal, .14, .74, .17)
      const beacon = add(new THREE.CylinderGeometry(.034, .034, .06, 16), lamps, -.135, .62, .16)
      const batteryBars: THREE.MeshStandardMaterial[] = []
      for (let i = 0; i < 5; i++) {
        const segment = new THREE.MeshStandardMaterial({ color: 0x73b9a0, emissive: 0x367660, emissiveIntensity: .4 })
        batteryBars.push(segment)
        add(new THREE.BoxGeometry(.042, .012, .025), segment, (i - 2) * .051, .579, .07)
      }
      // Reflective bumper strips and a rear service handle are actual geometry.
      const reflect = new THREE.MeshStandardMaterial({ color: 0xd4a549, roughness: .5, metalness: .2 })
      for (const x of [-.13, .13]) add(new THREE.BoxGeometry(.06, .04, .01), reflect, x, .49, .275)
      for (const x of [-.23, .23]) {
        add(new THREE.CylinderGeometry(.013, .013, .11, 8), metal, x, .39, .39)
      }
      const handle = add(new THREE.CylinderGeometry(.013, .013, .46, 8), metal, 0, .445, .39); handle.rotation.z = Math.PI / 2
      for (const x of [-.2, .2]) add(new THREE.BoxGeometry(.08, .026, .015), new THREE.MeshStandardMaterial({ color: 0xfff2d9, emissive: 0xffddab, emissiveIntensity: .8 }), x, .28, -.505)
      model.traverse(child => { if (child instanceof THREE.Mesh) { child.castShadow = true; child.receiveShadow = true }; child.userData.selection = root.userData.selection })
      const fallback = new THREE.Group()
      for (const child of [...root.children]) if (child !== root.userData.scan) fallback.add(child)
      const lod = new THREE.LOD(); lod.addLevel(model, 0); lod.addLevel(fallback, this.robotDistance(), .12); root.add(lod)
      root.userData.actorLod = lod
      this.robots.set(root, { model, wheels, head, lidar, beacon, lamps, heading: root.rotation.y, wheelAngles: [0, 0, 0, 0], batteryBars })
      this.mounted.add(model); this.track(model); root.userData.assetModelStatus = 'ready'
      this.changed(this.pending ? 'loading' : this.failed ? 'fallback' : 'ready')
    } catch {
      if (!this.disposed) { root.userData.assetModelStatus = 'fallback'; this.failed = true; this.retryJobs.set(root, () => this.robot(root)); this.changed('fallback') }
    } finally { this.attaching.delete(root); if (this.robots.has(root)) this.retryJobs.delete(root) }
  }

  /** Replace only failed visual assets; positions and running tasks stay intact. */
  async retryFailed(): Promise<void> {
    if (this.disposed || this.attaching.size || this.pending) return
    this.failed = false
    this.changed('loading')
    await Promise.allSettled([...this.retryJobs.values()].map(retry => retry()))
    if (!this.disposed) this.changed(this.retryJobs.size ? 'fallback' : 'ready')
  }

  updateRobot(root: THREE.Group, delta: number, distance: number, state: string, active: boolean, seconds: number, battery = 100) {
    const rig = this.robots.get(root)
    if (!rig) return
    // Pivot axes stay in ROS coordinates; wheel mesh orientation never accumulates drift.
    const turn = Math.atan2(Math.sin(root.rotation.y - rig.heading), Math.cos(root.rotation.y - rig.heading))
    rig.heading = root.rotation.y
    rig.wheels.forEach((wheel, index) => {
      if (active) rig.wheelAngles[index] = (rig.wheelAngles[index]! + (distance + (index % 2 ? 1 : -1) * turn * .2775) / .1651) % (Math.PI * 2)
      wheel.rotation.y = rig.wheelAngles[index]!
    })
    rig.batteryBars.forEach((material, index) => {
      const charged = Math.max(0, Math.min(100, battery)) > index * 20
      const color = !charged ? 0x293331 : battery < 20 ? 0xdba245 : 0x73b9a0
      material.color.setHex(color); material.emissive.setHex(charged ? color : 0x000000)
    })
    const scanning = ['sensing', 'inspecting', 'scanning', 'verifying'].includes(state)
    if (active && scanning) { rig.lidar.rotation.y += delta * 7; rig.head.rotation.y = Math.sin(seconds * .7) * .45 }
    else rig.head.rotation.y = 0
    const blocked = ['blocked', 'failed', 'low_battery'].includes(state)
    rig.lamps.color.setHex(blocked ? 0xe9ae4e : 0x91dfc3)
    rig.lamps.emissive.setHex(blocked ? 0xd88522 : 0x55d5af)
    rig.lamps.emissiveIntensity = active && scanning ? .9 + Math.sin(seconds * 4) * .35 : .55
  }

  private personDistance() { return this.quality === 'high' ? 65 : this.quality === 'medium' ? 40 : 18 }
  private robotDistance() { return this.quality === 'high' ? 80 : this.quality === 'medium' ? 50 : 22 }
  setQuality(quality: 'high' | 'medium' | 'low') {
    this.quality = quality
    for (const root of this.people.keys()) {
      const lod = root.userData.actorLod as THREE.LOD
      lod.levels[1]!.distance = this.personDistance(); lod.levels[2]!.distance = this.personDistance() * 2
    }
    for (const root of this.robots.keys()) (root.userData.actorLod as THREE.LOD).levels[1]!.distance = this.robotDistance()
  }

  private releaseResources() {
    for (const skeleton of this.skeletons) skeleton.dispose()
    for (const geometry of this.geometries) geometry.dispose()
    for (const material of this.materials) material.dispose()
    for (const texture of this.textures) texture.dispose()
    this.skeletons.clear(); this.geometries.clear(); this.materials.clear(); this.textures.clear()
  }
  dispose() {
    this.disposed = true
    for (const controller of this.transfers) controller.abort()
    this.transfers.clear()
    for (const rig of this.people.values()) { rig.mixer.stopAllAction(); rig.mixer.uncacheRoot(rig.mixer.getRoot()) }
    for (const model of this.mounted) model.removeFromParent()
    this.releaseResources(); this.people.clear(); this.robots.clear(); this.mounted.clear(); this.requests.clear(); this.retryJobs.clear(); this.attaching.clear()
  }
}
