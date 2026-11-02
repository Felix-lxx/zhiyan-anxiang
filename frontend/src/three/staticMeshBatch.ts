import * as THREE from 'three'
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js'

/** Bake inert fittings by material; preserve explicitly named interaction geometry. */
export function batchStaticParts(group:THREE.Group,keep:ReadonlySet<string>=new Set(),name='static-model-details') {
  const buckets=new Map<THREE.Material,THREE.Mesh[]>()
  for(const child of group.children){
    if(!(child instanceof THREE.Mesh)||child instanceof THREE.InstancedMesh||Array.isArray(child.material)||child.material.transparent||keep.has(child.name))continue
    const meshes=buckets.get(child.material)??[];meshes.push(child);buckets.set(child.material,meshes)
  }
  for(const [material,meshes] of buckets){
    if(meshes.length<2)continue
    const prepared=meshes.map(mesh=>{
      mesh.updateMatrix()
      const geometry=mesh.geometry.index?mesh.geometry.toNonIndexed():mesh.geometry.clone()
      return geometry.applyMatrix4(mesh.matrix)
    })
    const merged=mergeGeometries(prepared)
    prepared.forEach(geometry=>geometry.dispose())
    if(!merged)continue
    const batch=new THREE.Mesh(merged,material);batch.name=name;batch.castShadow=true;batch.receiveShadow=true
    group.add(batch)
    for(const mesh of meshes){mesh.removeFromParent();mesh.geometry.dispose()}
  }
}
