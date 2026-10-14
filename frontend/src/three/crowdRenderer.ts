import * as THREE from 'three'

/** All residents retain individual authoritative anchors. Only appearance is batched. */
export class CrowdRenderer {
  readonly group = new THREE.Group()
  private parts: THREE.InstancedMesh[]
  private transform = new THREE.Object3D()
  private color = new THREE.Color()
  private detailSlots: Array<{ model: THREE.Group; actor?: THREE.Group }> = []
  private lastSelection = -Infinity
  private preferred = ''
  private activeBudget = 0
  constructor(readonly actors: THREE.Group[], private makeDetail: () => THREE.Group) {
    const geometries = [
      new THREE.CapsuleGeometry(.2, .42, 2, 6), new THREE.SphereGeometry(.14, 6, 5),
      new THREE.BoxGeometry(.14, .65, .18), new THREE.BoxGeometry(.14, .65, .18),
      new THREE.RingGeometry(.29, .35, 12),
    ]
    this.parts = geometries.map((geometry, index) => {
      const material = index === 4
        ? new THREE.MeshBasicMaterial({ side: THREE.DoubleSide, transparent: true, opacity: .8, depthWrite: false })
        : new THREE.MeshStandardMaterial({ roughness: .9 })
      const mesh = new THREE.InstancedMesh(geometry, material, actors.length)
      mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage)
      mesh.frustumCulled = false // Bounds follow moving instances; no stale bind-pose sphere.
      mesh.userData.crowd = this
      this.group.add(mesh)
      return mesh
    })
  }

  selection(instanceId?: number) { return instanceId === undefined ? undefined : this.actors[instanceId]?.userData.selection }

  update(camera: THREE.Camera, selected: Set<string>, budget: number, time: number, moving: boolean,
    animate: (model: THREE.Group, actor: THREE.Group) => void) {
    const preferred = [...selected].join(',')
    if (time - this.lastSelection >= .5 || preferred !== this.preferred || budget !== this.activeBudget) {
      this.lastSelection = time; this.preferred = preferred; this.activeBudget = budget
      const nearby = this.actors.filter(a => a.visible).sort((a, b) =>
        Number(selected.has(b.name)) - Number(selected.has(a.name)) ||
        a.position.distanceToSquared(camera.position) - b.position.distanceToSquared(camera.position)).slice(0, budget)
      const wanted = new Set(nearby)
      for (const slot of this.detailSlots) if (slot.actor && !wanted.has(slot.actor)) {
        this.group.add(slot.model); slot.model.visible = false; slot.actor = undefined
      }
      for (const actor of nearby) {
        if (this.detailSlots.some(slot => slot.actor === actor)) continue
        let slot = this.detailSlots.find(item => !item.actor)
        if (!slot) { slot = { model: this.makeDetail() }; this.detailSlots.push(slot) }
        slot.actor = actor; actor.add(slot.model); slot.model.visible = true
        slot.model.userData.selection = actor.userData.selection
        slot.model.position.set(0, 0, 0); slot.model.rotation.set(0, 0, 0)
        slot.model.traverse(child => { child.userData.selection = actor.userData.selection })
      }
    }
    const detailed = new Set(this.detailSlots.filter(s => s.actor).map(s => s.actor))
    for (const slot of this.detailSlots) if (slot.actor) {
      for (const key of ['exposed', 'crowded', 'behaviorState', 'vulnerable', 'assisted']) slot.model.userData[key] = slot.actor.userData[key]
      animate(slot.model, slot.actor)
    }
    for (let i = 0; i < this.actors.length; i++) {
      const actor = this.actors[i]!
      const selectedActor = selected.has(actor.name)
      const danger = actor.userData.exposed, crowded = actor.userData.crowded
      const phase = moving && actor.userData.moved ? Math.sin(time * 7 + i * .63) * .34 : 0
      this.parts.forEach((part, index) => {
        const t = this.transform
        t.position.copy(actor.position); t.quaternion.copy(actor.quaternion)
        t.scale.setScalar(actor.visible && (index === 4 || !detailed.has(actor)) ? 1 : 0)
        if (index === 0) { t.position.y += 1.1; t.scale.z *= .7 }
        if (index === 1) t.position.y += 1.7
        if (index === 2 || index === 3) {
          t.translateX(index === 2 ? -.1 : .1); t.position.y += .43
          t.rotateX(index === 2 ? phase : -phase)
        }
        if (index === 4) { t.position.y += .03; t.rotation.set(-Math.PI / 2, 0, 0) }
        t.updateMatrix(); part.setMatrixAt(i, t.matrix)
        this.color.setHex(index === 4 ? selectedActor ? 0xffffff : danger ? 0xff4d2e : crowded ? 0xffc45d : actor.userData.vulnerable ? 0xf3be62 : 0x8ed0c2
          : index === 1 ? 0xc49674 : index >= 2 ? 0x34433e : [0x718478, 0x93674d, 0x576c83, 0x857383][i % 4]!)
        part.setColorAt(i, this.color)
      })
    }
    for (const part of this.parts) {
      part.instanceMatrix.needsUpdate = true
      // Raycasting also uses aggregate bounds, independently of frustum culling.
      // Recompute on the next click, otherwise moved crowds can become unselectable.
      part.boundingSphere = null
      if (part.instanceColor) part.instanceColor.needsUpdate = true
    }
  }
}
