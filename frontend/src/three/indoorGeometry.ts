import * as THREE from 'three'

export interface SpatialPoint { x: number; y: number; height: number }
export interface Passage { kind: string; width_meters: number; start: SpatialPoint; end: SpatialPoint }
export interface FloorRect { x: number; y: number; width: number; depth: number }

/** Slab geometry and furnishings use the same frozen passages as the walkers. */
export function stairOpenings(passages: Passage[], height: number): FloorRect[] {
  return passages.filter(edge => edge.kind === 'stairs' && Math.abs(edge.start.height - edge.end.height) > .05
    && height >= Math.min(edge.start.height, edge.end.height) - .01
    && height <= Math.max(edge.start.height, edge.end.height) + .01).map(edge => ({
    x: (edge.start.x + edge.end.x) / 2, y: (edge.start.y + edge.end.y) / 2,
    width: Math.abs(edge.end.x - edge.start.x) + edge.width_meters + .16,
    depth: Math.abs(edge.end.y - edge.start.y) + edge.width_meters + .16,
  }))
}

export function cutFloor(rect: FloorRect, holes: FloorRect[]): FloorRect[] {
  let parts = [rect]
  for (const hole of holes) parts = parts.flatMap(part => {
    const x0 = part.x - part.width / 2, x1 = part.x + part.width / 2
    const z0 = part.y - part.depth / 2, z1 = part.y + part.depth / 2
    const a = Math.max(x0, hole.x - hole.width / 2), b = Math.min(x1, hole.x + hole.width / 2)
    const c = Math.max(z0, hole.y - hole.depth / 2), d = Math.min(z1, hole.y + hole.depth / 2)
    if (a >= b || c >= d) return [part]
    return [[x0, a, z0, z1], [b, x1, z0, z1], [a, b, z0, c], [a, b, d, z1]]
      .filter(([l, r, t, u]) => r! - l! > .01 && u! - t! > .01)
      .map(([l, r, t, u]) => ({ x: (l! + r!) / 2, y: (t! + u!) / 2, width: r! - l!, depth: u! - t! }))
  })
  return parts
}

/** True only when a solid does not intersect any passage's walking envelope. */
export function furnitureFits(rect: FloorRect, height: number, passages: Passage[]): boolean {
  return passages.every(edge => {
    if (Math.max(edge.start.height, edge.end.height) + 1.8 < height || Math.min(edge.start.height, edge.end.height) > height + 2.1) return true
    const margin = Math.max(.32, edge.width_meters / 2)
    const box = new THREE.Box3(new THREE.Vector3(rect.x - rect.width / 2 - margin, height, rect.y - rect.depth / 2 - margin),
      new THREE.Vector3(rect.x + rect.width / 2 + margin, height + 2.1, rect.y + rect.depth / 2 + margin))
    const start = new THREE.Vector3(edge.start.x, edge.start.height + .05, edge.start.y)
    const end = new THREE.Vector3(edge.end.x, edge.end.height + .05, edge.end.y)
    if (box.containsPoint(start) || box.containsPoint(end)) return false
    const direction = end.clone().sub(start), distance = direction.length()
    if (distance < .0001) return true
    const hit = new THREE.Ray(start, direction.normalize()).intersectBox(box, new THREE.Vector3())
    return !hit || start.distanceTo(hit) > distance
  })
}

export function floorContainsHeight(height: number, floorHeight: number, below: number): boolean {
  // Include the complete downward stair flight; no disappearance halfway down.
  return height >= below - .05 && height <= floorHeight + .05
}
