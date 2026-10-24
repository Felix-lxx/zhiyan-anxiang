import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'

/** Local CC0 assets, cached per arena. Never put furniture outside its validated footprint. */
export class KitchenAssets {
  private cache = new Map<string, Promise<THREE.Group>>()
  private closed = false
  async fit(name: string, width: number, height: number, depth: number, worktopReference?: number) {
    if (this.closed) return null
    let pending = this.cache.get(name)
    if (!pending) {
      pending = new GLTFLoader().loadAsync(`/assets/kitchen/${name}.glb`).then(gltf => {
        if (this.closed) { this.release(gltf.scene); throw new Error('Arena closed') }
        return gltf.scene
      })
      this.cache.set(name, pending)
    }
    const source = await pending
    if (this.closed) return null
    const model = source.clone(true)
    const bounds = new THREE.Box3().setFromObject(model), size = bounds.getSize(new THREE.Vector3())
    const bottom = bounds.min.y
    const scale = Math.min(width / Math.max(size.x, .001), height / Math.max(size.y, .001), depth / Math.max(size.z, .001))
    model.scale.multiplyScalar(scale)
    bounds.setFromObject(model)
    model.position.set(-(bounds.min.x + bounds.max.x) / 2, -bounds.min.y, -(bounds.min.z + bounds.max.z) / 2)
    model.traverse(object => { if (object instanceof THREE.Mesh) { object.castShadow = true; object.receiveShadow = true } })
    const wrapper = new THREE.Group(); wrapper.add(model)
    wrapper.userData.fittedHeight = bounds.max.y - bounds.min.y
    if (worktopReference !== undefined) wrapper.userData.worktopHeight = (worktopReference-bottom)*scale
    return wrapper
  }
  private release(root: THREE.Object3D) {
    root.traverse(object => {
      if (!(object instanceof THREE.Mesh)) return
      object.geometry.dispose()
      for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
        material.map?.dispose(); material.dispose()
      }
    })
  }
  dispose() {
    this.closed = true
    for (const pending of this.cache.values()) void pending.then(root => this.release(root)).catch(() => {})
    this.cache.clear()
  }
}
