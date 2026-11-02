import * as THREE from 'three'

export interface LegChain { hip:THREE.Object3D; knee:THREE.Object3D; foot:THREE.Object3D }

function orientBone(bone:THREE.Object3D, from:THREE.Vector3, to:THREE.Vector3) {
  const world=bone.getWorldQuaternion(new THREE.Quaternion())
  world.premultiply(new THREE.Quaternion().setFromUnitVectors(from.normalize(),to.normalize()))
  const parent=bone.parent?.getWorldQuaternion(new THREE.Quaternion())??new THREE.Quaternion()
  bone.quaternion.copy(parent.invert().multiply(world));bone.updateWorldMatrix(false,true)
}

/** Lift a penetrating foot with a two-bone solve; never move the simulation root. */
export function plantFoot(chain:LegChain, supportY:number) {
  const {hip,knee,foot}=chain
  const a=hip.getWorldPosition(new THREE.Vector3()),b=knee.getWorldPosition(new THREE.Vector3()),c=foot.getWorldPosition(new THREE.Vector3())
  const lift=supportY-c.y
  if(!Number.isFinite(lift)||lift<=.001||lift>.45)return false
  const target=c.clone();target.y=supportY
  const upper=a.distanceTo(b),lower=b.distanceTo(c)
  if(upper<.001||lower<.001)return false
  const direction=target.clone().sub(a),distance=THREE.MathUtils.clamp(direction.length(),Math.abs(upper-lower)+.0001,upper+lower-.0001)
  direction.normalize()
  const pole=b.clone().sub(a).addScaledVector(direction,-b.clone().sub(a).dot(direction))
  if(pole.lengthSq()<1e-8){
    pole.set(0,0,-1).applyQuaternion(hip.getWorldQuaternion(new THREE.Quaternion()))
    pole.addScaledVector(direction,-pole.dot(direction))
    if(pole.lengthSq()<1e-8){
      pole.set(Math.abs(direction.x)<.9?1:0,0,Math.abs(direction.x)<.9?0:1)
      pole.addScaledVector(direction,-pole.dot(direction))
    }
  }
  pole.normalize()
  const cosine=THREE.MathUtils.clamp((upper*upper+distance*distance-lower*lower)/(2*upper*distance),-1,1)
  const desiredKnee=a.clone().addScaledVector(direction,upper*cosine).addScaledVector(pole,upper*Math.sqrt(1-cosine*cosine))
  const footRotation=foot.getWorldQuaternion(new THREE.Quaternion())
  orientBone(hip,b.clone().sub(a),desiredKnee.clone().sub(a))
  const k=knee.getWorldPosition(new THREE.Vector3()),f=foot.getWorldPosition(new THREE.Vector3())
  orientBone(knee,f.sub(k),target.clone().sub(k))
  foot.quaternion.copy((foot.parent?.getWorldQuaternion(new THREE.Quaternion())??new THREE.Quaternion()).invert().multiply(footRotation))
  foot.updateWorldMatrix(false,true)
  return true
}
