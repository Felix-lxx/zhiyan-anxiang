import * as THREE from 'three'
import { surfaceAssets, type PhotographicSurface } from './surfaceAssets'

export type SurfaceKind = 'plaster' | 'asphalt' | 'paving' | 'tile' | 'stone' | 'wood'

/** Local PBR surfaces with deterministic fallback. Each arena owns its resources. */
export class SceneMaterials {
  constructor(private changed: () => void = () => {}) {}
  private canvases = new Map<SurfaceKind, HTMLCanvasElement>()
  private textures = new Map<string, THREE.Texture>()
  private materials = new Map<string, THREE.MeshStandardMaterial>()
  private closed = false
  private highDetail = true
  private physicalMaps = new Map<string, THREE.Texture>()
  private physicalMaterials = new Map<THREE.MeshStandardMaterial, {
    normal: THREE.Texture
    roughness: THREE.Texture
  }>()

  cloneSurface(material: THREE.MeshStandardMaterial) {
    const clone = material.clone()
    const maps = this.physicalMaterials.get(material)
    if (maps) this.physicalMaterials.set(clone, maps)
    return clone
  }

  private photograph(kind: PhotographicSurface, channel: 'diff'|'nor_gl'|'rough', x: number, y: number, fallback?: HTMLCanvasElement) {
    const key = `${kind}:${channel}:${x}:${y}`
    const cached = this.physicalMaps.get(key)
    if (cached) return cached
    const texture: THREE.Texture = new THREE.Texture(fallback)
    texture.colorSpace = channel === 'diff' ? THREE.SRGBColorSpace : THREE.NoColorSpace
    texture.wrapS = texture.wrapT = THREE.RepeatWrapping
    texture.repeat.set(x, y); texture.anisotropy = 4
    if (fallback) texture.needsUpdate = true
    this.physicalMaps.set(key, texture)
    const url = `${import.meta.env.BASE_URL}assets/surfaces/${surfaceAssets[kind]}_${channel}_1k.jpg`
    new THREE.ImageLoader().load(url, image => {
      if (this.closed) return
      // WebGL immutable storage cannot resize a 256px fallback with a 1K
      // sub-image upload. Release its GPU allocation before replacing pixels.
      texture.dispose(); texture.image = image; texture.needsUpdate = true; this.changed()
    }, undefined, () => { /* Keep the operational procedural fallback. */ })
    return texture
  }

  setQuality(quality: 'low'|'medium'|'high') {
    this.highDetail = quality !== 'low'
    for (const [material, maps] of this.physicalMaterials) {
      material.normalMap = this.highDetail ? maps.normal : null
      material.roughnessMap = this.highDetail ? maps.roughness : null
      material.needsUpdate = true
    }
  }

  surface(kind: SurfaceKind, color: number, repeatX = 1, repeatY = 1) {
    const key = `${kind}:${color}:${repeatX}:${repeatY}`
    const existing = this.materials.get(key)
    if (existing) return existing
    let canvas = this.canvases.get(kind)
    if (!canvas) {
      canvas = document.createElement('canvas'); canvas.width = canvas.height = 256
      const context = canvas.getContext('2d')!
      let seed = 739
      const random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296 }
      context.fillStyle = kind === 'asphalt' ? '#9c9c9c' : '#d4d4d4'; context.fillRect(0, 0, 256, 256)
      for (let i = 0; i < 18000; i++) {
        const tone = Math.floor(120 + random() * 110)
        context.fillStyle = `rgba(${tone},${tone},${tone},${kind === 'asphalt' ? .65 : .25})`
        context.fillRect(random() * 256, random() * 256, 1 + random() * 2, 1 + random() * 2)
      }
      if (kind === 'tile') {
        context.fillStyle = '#ece9df'; context.fillRect(0, 0, 256, 256)
        context.strokeStyle = '#b8b7ae'; context.lineWidth = 3
        context.strokeRect(1.5, 1.5, 253, 253)
      } else if (kind === 'plaster') {
        for (let i = 0; i < 24; i++) {
          context.fillStyle = 'rgba(80,75,65,.035)'; context.fillRect(random() * 256, random() * 256, 2 + random() * 14, 15 + random() * 50)
        }
      } else if (kind === 'paving') {
        context.strokeStyle = '#858585'; context.lineWidth = 2
        for (let y = 0; y <= 256; y += 64) {
          context.beginPath(); context.moveTo(0, y); context.lineTo(256, y); context.stroke()
          for (let x = (y % 128 ? 32 : 0); x <= 256; x += 64) { context.beginPath(); context.moveTo(x, y); context.lineTo(x, y + 64); context.stroke() }
        }
      } else if (kind === 'wood') {
        context.fillStyle = '#ded1bb'; context.fillRect(0, 0, 256, 256)
        for (let i = 0; i < 85; i++) {
          const x = random() * 256
          context.strokeStyle = `rgba(100,80,55,${.04 + random() * .1})`; context.lineWidth = .5 + random()
          context.beginPath(); context.moveTo(x, 0); context.bezierCurveTo(x + 4, 80, x - 3, 170, x, 256); context.stroke()
        }
      } else if (kind === 'stone') {
        for (let i = 0; i < 8; i++) {
          context.strokeStyle = 'rgba(135,131,119,.13)'; context.lineWidth = .5
          context.beginPath(); context.moveTo(0, random()*256); context.bezierCurveTo(85, random()*256, 170, random()*256, 256, random()*256); context.stroke()
        }
      } else {
        context.strokeStyle = 'rgba(45,45,45,.3)'; context.lineWidth = 1
        context.beginPath(); context.moveTo(24, 56); context.lineTo(45, 99); context.lineTo(39, 129); context.lineTo(68, 158); context.stroke()
      }
      this.canvases.set(kind, canvas)
    }
    const map = new THREE.CanvasTexture(canvas); map.colorSpace = THREE.SRGBColorSpace
    map.wrapS = map.wrapT = THREE.RepeatWrapping; map.repeat.set(repeatX, repeatY); map.anisotropy = 4
    // Data maps must stay in linear space, separate from the albedo texture.
    const bump = new THREE.CanvasTexture(canvas); bump.wrapS = bump.wrapT = THREE.RepeatWrapping; bump.repeat.copy(map.repeat)
    const material = new THREE.MeshStandardMaterial({ color, map, bumpMap: bump, bumpScale: kind === 'asphalt' ? .045 : kind === 'stone' ? .003 : kind === 'tile' ? .008 : .014, roughness: kind === 'asphalt' ? .96 : kind === 'stone' ? .36 : kind === 'tile' ? .48 : kind === 'wood' ? .66 : .88 })
    if (kind in surfaceAssets) {
      const source = kind as PhotographicSurface
      material.map = this.photograph(source, 'diff', repeatX, repeatY, canvas)
      // A flat normal is used while the real OpenGL normal image decodes.
      const flat = document.createElement('canvas'); flat.width = flat.height = 1
      const ctx = flat.getContext('2d')!; ctx.fillStyle = '#8080ff'; ctx.fillRect(0, 0, 1, 1)
      const maps = {
        normal: this.photograph(source, 'nor_gl', repeatX, repeatY, flat),
        roughness: this.photograph(source, 'rough', repeatX, repeatY, canvas),
      }
      this.physicalMaterials.set(material, maps)
      material.normalMap = this.highDetail ? maps.normal : null
      material.roughnessMap = this.highDetail ? maps.roughness : null
      material.normalScale.setScalar(source === 'asphalt' ? .45 : .3)
      material.bumpMap = null
    }
    this.textures.set(key, map); this.textures.set(key + ':bump', bump); this.materials.set(key, material)
    return material
  }

  dispose() {
    this.closed = true
    const ownedMaterials = new Set([...this.materials.values(), ...this.physicalMaterials.keys()])
    ownedMaterials.forEach(material => material.dispose())
    this.textures.forEach(texture => texture.dispose())
    this.physicalMaps.forEach(texture => texture.dispose())
    this.physicalMaterials.clear()
    this.physicalMaps.clear()
    this.materials.clear()
    this.textures.clear()
    this.canvases.clear()
  }
}

/** Legacy simulation levels are 1.92 units apart. Ground-floor rooms render above the entrance slab. */
export function displayHeight(height = 0) { return height > 0 ? Math.max(0, height / 1.92 * 3.2 - 3.02) : height }
