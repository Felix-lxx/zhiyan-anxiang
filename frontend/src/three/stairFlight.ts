import * as THREE from 'three'

export interface StairSurface {
  start: THREE.Vector3
  end: THREE.Vector3
  width: number
  steps: number
}

/** Display treads and foot support derive from the same frozen endpoints. */
export function stairSurface(start: THREE.Vector3, end: THREE.Vector3, width: number): StairSurface {
  const [low, high] = start.y <= end.y ? [start, end] : [end, start]
  return { start: low.clone(), end: high.clone(), width, steps: Math.max(1, Math.ceil((high.y-low.y)/.18)) }
}

export function stairHeight(surface: StairSurface, x: number, z: number, reference: number): number | undefined {
  const dx=surface.end.x-surface.start.x, dz=surface.end.z-surface.start.z
  const length=Math.hypot(dx,dz)
  if(length<.001)return
  const px=x-surface.start.x, pz=z-surface.start.z
  const along=(px*dx+pz*dz)/(length*length)
  const lateral=Math.abs(px*dz-pz*dx)/length
  if(along<-.12/length||along>1+.12/length||lateral>surface.width/2)return
  const index=along>=1-1e-6?surface.steps:Math.max(0,Math.floor(along*surface.steps))
  const height=surface.start.y+(surface.end.y-surface.start.y)*index/surface.steps
  return Math.abs(height-reference)<=.55?height:undefined
}

export function createStairFlight(surface: StairSurface) {
  const root=new THREE.Group();root.name='continuous-stair-flight'
  const {start,end,width,steps}=surface, rise=end.y-start.y
  const run=Math.hypot(end.x-start.x,end.z-start.z), depth=run/steps, riser=rise/steps
  root.position.copy(start);root.rotation.y=Math.atan2(end.x-start.x,end.z-start.z)
  const concrete=new THREE.MeshStandardMaterial({color:0xaaa99d,roughness:.92})
  const steel=new THREE.MeshStandardMaterial({color:0x536966,roughness:.42,metalness:.65})
  const rubber=new THREE.MeshStandardMaterial({color:0x454d48,roughness:.95})
  function batch(name:string,geometry:THREE.BufferGeometry,material:THREE.Material,count:number){
    const mesh=new THREE.InstancedMesh(geometry,material,count);mesh.name=name;mesh.receiveShadow=true;mesh.castShadow=true;root.add(mesh);return mesh
  }
  const treads=batch('solid-stair-treads',new THREE.BoxGeometry(width,riser+.16,depth+.002),concrete,steps)
  const nosings=batch('anti-slip-nosings',new THREE.BoxGeometry(width-.06,.008,Math.min(.035,depth*.2)),rubber,steps)
  const heat=new THREE.InstancedMesh(new THREE.PlaneGeometry(Math.max(.1,width-.12),Math.max(.01,depth-.02)),new THREE.MeshBasicMaterial({color:0x54d4a4,transparent:true,opacity:.2,depthWrite:false,side:THREE.DoubleSide}),steps)
  heat.name='stair-density-treads';heat.frustumCulled=false;root.add(heat)
  const transform=new THREE.Object3D()
  for(let i=0;i<steps;i++){
    const top=i*riser
    transform.position.set(0,top-(riser+.16)/2,(i+.5)*depth);transform.rotation.set(0,0,0);transform.updateMatrix();treads.setMatrixAt(i,transform.matrix)
    transform.position.set(0,top+.006,(i+.04)*depth);transform.updateMatrix();nosings.setMatrixAt(i,transform.matrix)
    transform.position.set(0,top+.012,(i+.5)*depth);transform.rotation.x=-Math.PI/2;transform.updateMatrix();heat.setMatrixAt(i,transform.matrix)
  }
  const slab=new THREE.Mesh(new THREE.BoxGeometry(width,.1,Math.hypot(run,rise)),concrete)
  slab.position.set(0,rise/2-.28,run/2);slab.rotation.x=-Math.atan2(rise,run);slab.receiveShadow=true;root.add(slab)
  for(const [z,y] of [[0,0],[run,rise]]){
    const landing=new THREE.Mesh(new THREE.BoxGeometry(width,.12,.24),concrete);landing.position.set(0,y-.06,z);landing.receiveShadow=true;root.add(landing)
  }
  if(rise>.35)for(const side of [-1,1]){
    const x=side*(width/2+.035)
    const rail=new THREE.Mesh(new THREE.CylinderGeometry(.025,.025,Math.hypot(run,rise),10),steel)
    rail.position.set(x,rise/2+.95,run/2);rail.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),new THREE.Vector3(0,rise,run).normalize());root.add(rail)
    const count=Math.max(2,Math.ceil(run/.8))
    for(let i=0;i<=count;i++){
      const t=i/count, support=t>=1?rise:Math.floor(t*steps)*riser, height=.95+rise*t-support
      const post=new THREE.Mesh(new THREE.CylinderGeometry(.018,.018,height,8),steel);post.position.set(x,support+height/2,t*run);root.add(post)
    }
  }
  return {group:root,heat}
}
