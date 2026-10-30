import * as THREE from 'three'

export interface SpatialPoint { x: number; y: number; height: number }
export interface Passage { id?: string; kind: string; width_meters: number; start: SpatialPoint; end: SpatialPoint }
export interface FloorRect { x: number; y: number; width: number; depth: number }

/** Partial front walls around the real doorway, never an unbroken room box. */
export function doorWallPanels(room: FloorRect, opening: {x:number;y:number;width:number;rotation:number}): FloorRect[] {
  const nx = Math.sin(opening.rotation), ny = Math.cos(opening.rotation)
  // Historical diagonal doors need their original unobstructed presentation.
  if (Math.abs(nx) > .001 && Math.abs(ny) > .001) return []
  const span = Math.abs(ny) > .5 ? room.width : room.depth
  const center = (room.x-opening.x)*ny - (room.y-opening.y)*nx
  const intervals = [[center-span/2, -opening.width/2-.08], [opening.width/2+.08, center+span/2]]
  return intervals.filter(([a,b]) => b! - a! > .08).map(([a,b]) => {
    const offset = (a!+b!)/2, length = b!-a!
    return {x:opening.x+ny*offset,y:opening.y-nx*offset,
      width:Math.abs(ny)>.5?length:.08,depth:Math.abs(ny)>.5?.08:length}
  })
}

/** Place the door perpendicular to its authoritative passage, at the room boundary. */
export function doorPortal(room: FloorRect, hall: {x:number;y:number}, width:number) {
  const dx=hall.x-room.x, dy=hall.y-room.y
  const t=Math.min(1,Math.abs(dx)>.001?room.width/(2*Math.abs(dx)):Infinity,
    Math.abs(dy)>.001?room.depth/(2*Math.abs(dy)):Infinity)
  return {x:room.x+dx*t,y:room.y+dy*t,rotation:Math.atan2(dx,dy),width:Math.max(.1,width),
    // Park the open leaf on the room side and outside the walking envelope.
    hingeX:-Math.max(.1,width)/2-.04,openAngle:Math.PI/2}
}

/** Frame an entire floor in both wide preview canvases and narrow phone viewports. */
export function indoorCameraOffset(width: number, depth: number, aspect: number): THREE.Vector3 {
  const direction = new THREE.Vector3(10, 13, 16).normalize()
  const horizontal = new THREE.Vector3(16, 0, -10).normalize()
  const vertical = new THREE.Vector3().crossVectors(direction, horizontal).normalize()
  const halfWidth = (Math.abs(horizontal.x) * width + Math.abs(horizontal.z) * depth) / 2
  const halfHeight = (Math.abs(vertical.x) * width + Math.abs(vertical.z) * depth + Math.abs(vertical.y) * 2.4) / 2
  // Add the depth extent so near corners remain inside the perspective frustum.
  const nearExtent = (direction.x * width + direction.z * depth) / 2
  const distance = Math.max(halfHeight, halfWidth / Math.max(.3, aspect)) / Math.tan(24 * Math.PI / 180) + nearExtent * .5
  return direction.multiplyScalar(Math.max(6, distance))
}

/** Fit all eligible ignition objects, including their visible height and footprint. */
export function fireSourceCamera(objects: FloorRect[], aspect: number) {
  const bounds = new THREE.Box3()
  for (const object of objects) {
    bounds.expandByPoint(new THREE.Vector3(object.x-object.width/2, 0, object.y-object.depth/2))
    bounds.expandByPoint(new THREE.Vector3(object.x+object.width/2, 4, object.y+object.depth/2))
  }
  const target = bounds.getCenter(new THREE.Vector3())
  const direction = new THREE.Vector3(24,32,30).normalize()
  const right = new THREE.Vector3(direction.z,0,-direction.x).normalize()
  const up = new THREE.Vector3().crossVectors(direction,right).normalize()
  const tangent = Math.tan(24*Math.PI/180)
  let distance = 10
  if (!bounds.isEmpty()) for (const x of [bounds.min.x,bounds.max.x]) for (const y of [bounds.min.y,bounds.max.y]) for (const z of [bounds.min.z,bounds.max.z]) {
    const point = new THREE.Vector3(x,y,z).sub(target)
    distance = Math.max(distance, point.dot(direction) + 1.15*Math.max(Math.abs(point.dot(right))/(tangent*Math.max(.1,aspect)),Math.abs(point.dot(up))/tangent))
  }
  return { target, position: target.clone().addScaledVector(direction,distance) }
}

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
