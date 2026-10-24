import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'

/** Local CC0 assets, cached per arena. Never put furniture outside its validated footprint. */
export class KitchenAssets {
  private cache = new Map<string, Promise<THREE.Group>>()
  private requests = new Set<AbortController>()
  private closed = false
  async fit(name: string, width: number, height: number, depth: number, worktopReference?: number) {
    if (this.closed) return null
    if (![width, height, depth].every(value => Number.isFinite(value) && value > 0))
      throw new Error('厨房模型尺寸无效')
    if (!/^[a-zA-Z0-9_-]+$/.test(name)) throw new Error('厨房资产名称无效')
    let pending = this.cache.get(name)
    if (!pending) {
      const controller = new AbortController()
      this.requests.add(controller)
      const timeout = setTimeout(() => controller.abort(), 12000)
      pending = fetch(`/assets/kitchen/${name}.glb`, { signal: controller.signal }).then(async response => {
        if (!response.ok) throw new Error(`厨房模型加载失败 (${response.status})`)
        return new GLTFLoader().parseAsync(await response.arrayBuffer(), '/assets/kitchen/')
      }).then(gltf => {
        if (this.closed) { this.release(gltf.scene); throw new Error('Arena closed') }
        return gltf.scene
      }).catch(error => {
        // A rejected cached promise otherwise poisons every subsequent attempt.
        this.cache.delete(name)
        throw error
      }).finally(() => {
        clearTimeout(timeout)
        this.requests.delete(controller)
      })
      this.cache.set(name, pending)
    }
    const source = await pending
    if (this.closed) return null
    const model = source.clone(true)
    const bounds = new THREE.Box3().setFromObject(model), size = bounds.getSize(new THREE.Vector3())
    if (![size.x, size.y, size.z].every(value => Number.isFinite(value) && value > .00001))
      throw new Error('厨房模型几何为空或尺寸无效')
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
    for (const controller of this.requests) controller.abort()
    this.requests.clear()
    for (const pending of this.cache.values()) void pending.then(root => this.release(root)).catch(() => {})
    this.cache.clear()
  }
}
