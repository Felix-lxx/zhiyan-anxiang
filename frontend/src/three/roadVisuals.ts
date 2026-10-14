import * as THREE from 'three'

export interface VisualRoad {
  id: string
  name: string
  start: { x: number; y: number }
  end: { x: number; y: number }
  width_meters: number
  status: 'open' | 'restricted' | 'blocked'
  risk_score: number
  density_percent?: number
}

/** Road geometry is static; risk, capacity and availability are live projections. */
export class RoadVisuals {
  readonly group = new THREE.Group()
  readonly meshes = new Map<string, THREE.Mesh<THREE.BoxGeometry, THREE.MeshStandardMaterial>>()
  heat: THREE.InstancedMesh<THREE.BoxGeometry, THREE.MeshBasicMaterial> | null = null
  private topology = ''

  update(edges: VisualRoad[], detail: (edge: VisualRoad) => string): boolean {
    const topology = JSON.stringify(edges.map(edge => [edge.id, edge.start.x, edge.start.y, edge.end.x, edge.end.y, edge.width_meters]))
    const rebuilt = topology !== this.topology
    if (rebuilt) {
      this.dispose()
      this.topology = topology
      if (edges.length) {
        this.heat = new THREE.InstancedMesh(
          new THREE.BoxGeometry(1, .05, 1),
          new THREE.MeshBasicMaterial({ transparent: true, opacity: .36, depthWrite: false, blending: THREE.AdditiveBlending }),
          edges.length,
        )
        this.heat.frustumCulled = false
        this.group.add(this.heat)
      }
    }
    const transform = new THREE.Object3D()
    edges.forEach((edge, index) => {
      const risk = THREE.MathUtils.clamp(edge.risk_score / 100, 0, 1)
      const density = THREE.MathUtils.clamp((edge.density_percent ?? 0) / 100, 0, 1)
      const color = new THREE.Color(edge.status === 'blocked' ? 0xff352c : edge.status === 'restricted' ? 0xffa637 : 0x39c99b)
      if (edge.status === 'open') color.lerp(new THREE.Color(0xff4935), Math.max(risk, density))
      let mesh = this.meshes.get(edge.id)
      if (!mesh) {
        const length = Math.hypot(edge.end.x - edge.start.x, edge.end.y - edge.start.y)
        const width = Math.max(1.8, edge.width_meters * .72)
        mesh = new THREE.Mesh(new THREE.BoxGeometry(width, .16, length), new THREE.MeshStandardMaterial({ roughness: .76, metalness: .08, transparent: true, depthWrite: false }))
        mesh.position.set((edge.start.x + edge.end.x) / 2 - 50, .22, (edge.start.y + edge.end.y) / 2 - 50)
        mesh.rotation.y = Math.atan2(edge.end.x - edge.start.x, edge.end.y - edge.start.y)
        mesh.receiveShadow = true
        this.meshes.set(edge.id, mesh)
        this.group.add(mesh)
        transform.position.copy(mesh.position); transform.position.y = .36
        transform.rotation.copy(mesh.rotation); transform.scale.set(width * .28, 1, Math.max(.2, length * .96)); transform.updateMatrix()
        this.heat?.setMatrixAt(index, transform.matrix)
      }
      mesh.material.color.copy(color).multiplyScalar(.58)
      mesh.material.emissive.setHex(edge.status === 'blocked' ? 0x7e160f : density > .65 ? 0x6a2e0b : 0)
      mesh.material.emissiveIntensity = edge.status === 'blocked' ? .62 : density > .65 ? .28 : 0
      mesh.material.opacity = edge.status === 'blocked' ? .72 : .24 + density * .18
      mesh.userData.selection = {
        title: edge.name, type: '真实道路路段', detail: detail(edge),
        action: edge.status === 'blocked' ? undefined : 'channel_blocked', roadEdgeId: edge.id,
        x: (edge.start.x + edge.end.x) / 2, y: (edge.start.y + edge.end.y) / 2,
      }
      this.heat?.setColorAt(index, color)
    })
    if (this.heat) {
      if (rebuilt) this.heat.instanceMatrix.needsUpdate = true
      if (this.heat.instanceColor) this.heat.instanceColor.needsUpdate = true
    }
    return rebuilt
  }

  dispose() {
    for (const mesh of this.meshes.values()) { mesh.geometry.dispose(); mesh.material.dispose() }
    this.heat?.geometry.dispose(); this.heat?.material.dispose(); this.heat?.dispose()
    this.group.clear(); this.meshes.clear(); this.heat = null; this.topology = ''
  }
}
