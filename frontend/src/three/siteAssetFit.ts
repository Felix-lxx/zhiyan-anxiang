import * as THREE from 'three'

/** Uniform scaling preserves proportions; reserve the full AABB including leaves/handles. */
export function fitSiteAsset(source:THREE.Object3D,width:number,depth:number,height:number,alignLongAxis=false) {
  if(![width,depth,height].every(n=>Number.isFinite(n)&&n>0))throw new Error('Invalid asset envelope')
  const model=new THREE.Group(), body=source.clone(true)
  model.add(body);body.updateWorldMatrix(true,true)
  let bounds=new THREE.Box3().setFromObject(body), size=bounds.getSize(new THREE.Vector3())
  if(alignLongAxis && (width>depth)!==(size.x>size.z)) {
    body.rotation.y+=Math.PI/2;body.updateWorldMatrix(true,true)
    bounds=new THREE.Box3().setFromObject(body);size=bounds.getSize(new THREE.Vector3())
  }
  if(![size.x,size.y,size.z].every(n=>Number.isFinite(n)&&n>1e-5))throw new Error('Empty asset geometry')
  const scale=Math.min(width/size.x,depth/size.z,height/size.y)
  const center=bounds.getCenter(new THREE.Vector3())
  // Translate outside the source transform: glTF roots may already carry rotations/scales.
  const pivot=new THREE.Group();model.remove(body);pivot.add(body);model.add(pivot)
  pivot.position.set(-center.x,-bounds.min.y,-center.z);model.scale.setScalar(scale)
  model.updateWorldMatrix(true,true)
  return model
}
