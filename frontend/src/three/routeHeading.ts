import type { Vector3 } from 'three'

/** Recover orientation at a confirmed position; never extrapolate along a future route. */
export function routeHeading(position: Vector3, route: Vector3[]): number | undefined {
  let nearest = Infinity, heading: number | undefined
  for (let i = 1; i < route.length; i++) {
    const a = route[i - 1]!, direction = route[i]!.clone().sub(a)
    const length = direction.lengthSq()
    if (length < 1e-8) continue
    const t = Math.max(0, Math.min(1, position.clone().sub(a).dot(direction) / length))
    const distance = a.clone().addScaledVector(direction, t).distanceToSquared(position)
    if (distance < nearest) {
      nearest = distance
      if (direction.x ** 2 + direction.z ** 2 > 1e-8) heading = Math.atan2(-direction.x, -direction.z)
    }
  }
  return nearest < .0064 ? heading : undefined
}
