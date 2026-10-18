import * as THREE from 'three'

/** Presentation only. Never extrapolates beyond a server-confirmed position. */
export class ActorMotion {
  private tracks = new Map<THREE.Object3D, { target: THREE.Vector3; route: THREE.Vector3[]; path: THREE.Vector3[]; cursor: number; speed: number; stamp: number; received: number }>()

  accept(object: THREE.Object3D, target: THREE.Vector3, route: THREE.Vector3[], stamp: number, animate: boolean, now = performance.now()) {
    const incomingRoute = route
    let nearest = Infinity, segmentIndex = -1
    for (let i = 1; i < route.length; i++) {
      const a = route[i - 1]!, segment = route[i]!.clone().sub(a)
      const t = THREE.MathUtils.clamp(target.clone().sub(a).dot(segment) / Math.max(.000001, segment.lengthSq()), 0, 1)
      const distance = a.clone().addScaledVector(segment, t).distanceToSquared(target)
      if (distance < nearest) { nearest = distance; segmentIndex = i }
    }
    route = nearest < .04 ? [target.clone(), ...route.slice(segmentIndex)] : []
    const previous = this.tracks.get(object)
    if (!previous || !animate || stamp < previous.stamp || now - previous.received > 3000) {
      object.position.copy(target)
      this.tracks.set(object, { target: target.clone(), route, path: [], cursor: 0, speed: 0, stamp, received: now })
      return
    }
    // Selection changes and unrelated snapshots must not restart interpolation.
    if (previous.target.distanceToSquared(target) < .000001) {
      if (stamp !== previous.stamp) { previous.received = now; previous.stamp = stamp }
      previous.route = route
      return
    }
    const source = previous.path.slice(previous.cursor).concat(previous.route)
    // A reversed route can still contain the rendered position. Use its real
    // vertices when available instead of a straight line to the next snapshot.
    const path = this.confirmedPath(object.position, target, source)
      ?? this.pathOnNewRoute(object.position, target, incomingRoute)
    if (!path) {
      object.position.copy(target)
      this.tracks.set(object, { target: target.clone(), route, path: [], cursor: 0, speed: 0, stamp, received: now })
      return
    }
    let distance = 0, point = object.position
    for (const next of path) { distance += point.distanceTo(next); point = next }
    const duration = THREE.MathUtils.clamp((now - previous.received) / 1000, .12, 1.2)
    this.tracks.set(object, { target: target.clone(), route, path, cursor: 0, speed: distance / duration, stamp, received: now })
  }

  private pathOnNewRoute(start: THREE.Vector3, target: THREE.Vector3, route: THREE.Vector3[]) {
    // Reversal/replanning is safe to interpolate only when both positions lie
    // on the new polyline in forward order. Otherwise reconcile, never guess.
    for (let i = 1; i < route.length; i++) {
      const a = route[i - 1]!, segment = route[i]!.clone().sub(a)
      const t = THREE.MathUtils.clamp(start.clone().sub(a).dot(segment) / Math.max(.000001, segment.lengthSq()), 0, 1)
      if (a.clone().addScaledVector(segment, t).distanceTo(start) < .08) {
        const path = this.confirmedPath(start, target, route.slice(i))
        if (path) return path
      }
    }
    return null
  }

  private confirmedPath(start: THREE.Vector3, target: THREE.Vector3, route: THREE.Vector3[]) {
    // Only retain corners up to a target lying on the known route. Do not invent a
    // route after replanning, a rewind, or a disconnected snapshot.
    const points = [start, ...route.filter((p, i) => i === 0 || p.distanceToSquared(route[i - 1]!) > .000001)]
    for (let i = 1; i < points.length; i++) {
      const a = points[i - 1]!, b = points[i]!, segment = b.clone().sub(a)
      const t = THREE.MathUtils.clamp(target.clone().sub(a).dot(segment) / Math.max(.000001, segment.lengthSq()), 0, 1)
      if (a.clone().addScaledVector(segment, t).distanceTo(target) < .08) return [...points.slice(1, i), target.clone()]
    }
    // A new route can invalidate the old corridor. Reconcile to authority rather
    // than drawing a fictitious diagonal through a wall or closed road.
    return null
  }

  step(object: THREE.Object3D, delta: number, animate: boolean): number {
    const track = this.tracks.get(object)
    if (!track) return 0
    if (!animate) { object.position.copy(track.target); track.path = []; return 0 }
    let budget = track.speed * delta, travelled = 0
    while (budget > 0 && track.cursor < track.path.length) {
      const target = track.path[track.cursor]!, direction = target.clone().sub(object.position), distance = direction.length()
      const step = Math.min(distance, budget)
      if (distance > .00001) {
        object.position.addScaledVector(direction, step / distance)
        if (direction.x ** 2 + direction.z ** 2 > .000001) {
          const yaw = Math.atan2(-direction.x, -direction.z)
          const change = Math.atan2(Math.sin(yaw - object.rotation.y), Math.cos(yaw - object.rotation.y))
          object.rotation.y += change * Math.min(1, delta * 14)
        }
      }
      travelled += step; budget -= step
      if (distance <= step + .00001) { object.position.copy(target); track.cursor++ } else break
    }
    return travelled
  }

  clear() { this.tracks.clear() }
}
