import * as THREE from 'three'

/** Procedural, deterministic, offline surface maps. Each arena owns its resources. */
export class SceneMaterials {
  private textures = new Map<string, THREE.Texture>()
  private materials = new Map<string, THREE.MeshStandardMaterial>()

  surface(kind: 'plaster' | 'asphalt' | 'paving', color: number, repeatX = 1, repeatY = 1) {
    const key = `${kind}:${color}:${repeatX}:${repeatY}`
    const existing = this.materials.get(key)
    if (existing) return existing
    const canvas = document.createElement('canvas'); canvas.width = canvas.height = 256
    const context = canvas.getContext('2d')!
    let seed = 739
    const random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296 }
    context.fillStyle = kind === 'asphalt' ? '#9c9c9c' : '#d4d4d4'; context.fillRect(0, 0, 256, 256)
    for (let i = 0; i < 18000; i++) {
      const tone = Math.floor(120 + random() * 110)
      context.fillStyle = `rgba(${tone},${tone},${tone},${kind === 'asphalt' ? .65 : .25})`
      context.fillRect(random() * 256, random() * 256, 1 + random() * 2, 1 + random() * 2)
    }
    if (kind === 'plaster') {
      for (let i = 0; i < 24; i++) {
        context.fillStyle = 'rgba(80,75,65,.035)'; context.fillRect(random() * 256, random() * 256, 2 + random() * 14, 15 + random() * 50)
      }
    } else if (kind === 'paving') {
      context.strokeStyle = '#858585'; context.lineWidth = 2
      for (let y = 0; y <= 256; y += 64) {
        context.beginPath(); context.moveTo(0, y); context.lineTo(256, y); context.stroke()
        for (let x = (y % 128 ? 32 : 0); x <= 256; x += 64) { context.beginPath(); context.moveTo(x, y); context.lineTo(x, y + 64); context.stroke() }
      }
    } else {
      context.strokeStyle = 'rgba(45,45,45,.3)'; context.lineWidth = 1
      context.beginPath(); context.moveTo(24, 56); context.lineTo(45, 99); context.lineTo(39, 129); context.lineTo(68, 158); context.stroke()
    }
    const map = new THREE.CanvasTexture(canvas); map.colorSpace = THREE.SRGBColorSpace
    map.wrapS = map.wrapT = THREE.RepeatWrapping; map.repeat.set(repeatX, repeatY); map.anisotropy = 4
    // Data maps must stay in linear space, separate from the albedo texture.
    const bump = new THREE.CanvasTexture(canvas); bump.wrapS = bump.wrapT = THREE.RepeatWrapping; bump.repeat.copy(map.repeat)
    const material = new THREE.MeshStandardMaterial({ color, map, bumpMap: bump, bumpScale: kind === 'asphalt' ? .055 : .025, roughness: kind === 'asphalt' ? .94 : .86 })
    this.textures.set(key, map); this.textures.set(key + ':bump', bump); this.materials.set(key, material)
    return material
  }

  dispose() { this.materials.forEach(m => m.dispose()); this.textures.forEach(t => t.dispose()); this.materials.clear(); this.textures.clear() }
}

/** Legacy simulation levels are 1.92 units apart. Ground-floor rooms render above the entrance slab. */
export function displayHeight(height = 0) { return height > 0 ? Math.max(0, height / 1.92 * 3.2 - 3.02) : height }
