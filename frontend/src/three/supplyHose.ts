import * as THREE from 'three'
import { ROAD_SURFACE_Y } from './roadSurface'

export const HOSE_RADIUS = .065

/** Clamp the tube centreline, not just control points: cubic splines overshoot. */
export function supplyHoseCurve(source: THREE.Vector3, pump: THREE.Vector3, route: THREE.Vector3[] = []): THREE.Curve<THREE.Vector3> {
  if (route.length > 2) {
    // Keep server-confirmed corners. Cubic interpolation can cut a building
    // even when all of its control points lie outside the walls.
    const ground = ROAD_SURFACE_Y + HOSE_RADIUS + .025
    const points = [source.clone(), new THREE.Vector3(source.x, ground, source.z),
      ...route.slice(1, -1).map(point => new THREE.Vector3(point.x, ground, point.z)),
      new THREE.Vector3(pump.x, ground, pump.z), pump.clone()]
    const curve = new THREE.CurvePath<THREE.Vector3>()
    for (let index = 1; index < points.length; index++) {
      if (points[index]!.distanceToSquared(points[index - 1]!) > 1e-10) {
        curve.add(new THREE.LineCurve3(points[index - 1]!, points[index]!))
      }
    }
    return curve
  }
  const nearSource = source.clone().lerp(pump, .12)
  const nearPump = source.clone().lerp(pump, .88)
  nearSource.y = nearPump.y = ROAD_SURFACE_Y + HOSE_RADIUS + .025
  const spline = new THREE.CatmullRomCurve3([source.clone(), nearSource, nearPump, pump.clone()], false, 'centripetal')
  return new class extends THREE.Curve<THREE.Vector3> {
    constructor() { super() }

    getPoint(t: number, target = new THREE.Vector3()) {
      spline.getPoint(THREE.MathUtils.clamp(t, 0, 1), target)
      target.y = Math.max(ROAD_SURFACE_Y + HOSE_RADIUS + .005, target.y)
      return target
    }
  }()
}
