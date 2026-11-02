import * as THREE from 'three'

export interface VehicleWheel {object:THREE.Object3D;radius:number;rest:THREE.Quaternion;front:boolean;rollSign?:number}

/** Preserve imported proportions and orient the authored front toward simulation -Z. */
export function fitVehicleModel(model:THREE.Group,length:number,maxWidth:number){
  model.updateMatrixWorld(true)
  const front:THREE.Vector3[]=[],back:THREE.Vector3[]=[]
  model.traverse(object=>{
    if(object.name.startsWith('wheel-front'))front.push(object.getWorldPosition(new THREE.Vector3()))
    if(object.name.startsWith('wheel-back'))back.push(object.getWorldPosition(new THREE.Vector3()))
  })
  const average=(points:THREE.Vector3[])=>points.reduce((a,b)=>a.add(b),new THREE.Vector3()).multiplyScalar(1/points.length)
  const before=new THREE.Box3().setFromObject(model).getSize(new THREE.Vector3())
  if(!before.toArray().every(Number.isFinite)||Math.min(before.x,before.y,before.z)<.01)throw new Error('车辆模型缺少有效三维尺寸')
  const direction=front.length&&back.length?average(front).sub(average(back)):new THREE.Vector3(before.x>before.z?1:0,0,before.x>before.z?0:1)
  model.rotation.y+=Math.PI-Math.atan2(direction.x,direction.z)
  model.updateMatrixWorld(true)
  const box=new THREE.Box3().setFromObject(model),size=box.getSize(new THREE.Vector3()),center=box.getCenter(new THREE.Vector3())
  const factor=Math.min(length/Math.max(size.z,.01),maxWidth/Math.max(size.x,.01))
  model.position.sub(new THREE.Vector3(center.x,box.min.y,center.z)).multiplyScalar(factor);model.scale.multiplyScalar(factor)
  model.updateMatrixWorld(true)
  const wheels:VehicleWheel[]=[]
  model.traverse(object=>{
    if(!object.name.startsWith('wheel-'))return
    const bounds=new THREE.Box3().setFromObject(object).getSize(new THREE.Vector3())
    wheels.push({object,radius:Math.max(.05,bounds.y/2),rest:object.quaternion.clone(),front:object.name.includes('front')})
  })
  return wheels
}

/** Wheels roll around their own axle; steering never moves the authoritative vehicle. */
export function poseVehicleWheels(wheels:VehicleWheel[],distance:number,steering:number){
  for(const wheel of wheels){
    const roll=(Number(wheel.object.userData.wheelRoll??0)+distance/wheel.radius*(wheel.rollSign??1))%(Math.PI*2)
    wheel.object.userData.wheelRoll=roll
    wheel.object.quaternion.copy(wheel.rest)
    wheel.object.quaternion.premultiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1,0,0),roll))
    wheel.object.quaternion.premultiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0),wheel.front?steering:0))
  }
}

/** The packaged ambulance has separate rear leaves with outer-edge pivots. */
export function poseAmbulanceRearDoors(model:THREE.Object3D, openness:number){
  const left=model.getObjectByName('door-left'),right=model.getObjectByName('door-right')
  if(!left||!right)return false
  const angle=THREE.MathUtils.clamp(openness,0,1)*Math.PI*.46
  left.rotation.y=-angle
  right.rotation.y=angle
  return true
}
