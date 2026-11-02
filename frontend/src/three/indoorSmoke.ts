import * as THREE from 'three'

/** A bounded visual projection of zone density; never advances the fire model. */
export class IndoorSmoke {
  readonly mesh:THREE.InstancedMesh<THREE.SphereGeometry,THREE.MeshBasicMaterial>
  private density=0
  private transform=new THREE.Object3D()
  constructor(private width:number,private depth:number,seed:number){
    this.mesh=new THREE.InstancedMesh(new THREE.SphereGeometry(1,12,8),new THREE.MeshBasicMaterial({color:0xb7bab2,transparent:true,opacity:0,depthWrite:false}),32)
    this.mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage)
    this.mesh.name='zone-smoke-clouds';this.mesh.frustumCulled=false;this.mesh.renderOrder=3
    this.mesh.userData.phase=seed*.73
    this.step(0)
  }
  update(density:number,temperature:number){
    this.density=THREE.MathUtils.clamp(density,0,1)
    this.mesh.visible=this.density>.008
    this.mesh.material.opacity=Math.min(.16,this.density*.19)
    this.mesh.material.color.setHex(temperature>100?0x666b68:0xb8bcb6)
  }
  step(seconds:number,quality=1){
    const count=quality<.6?12:quality<1?20:32
    this.mesh.count=count
    this.mesh.material.opacity=Math.min(.35,this.density*.15*32/count)
    for(let i=0;i<count;i++){
      const phase=i*2.399+Number(this.mesh.userData.phase),r=Math.min(.38,this.width*.22,this.depth*.22)
      const radius=r*(.7+.3*Math.sin(phase+1)**2)
      const layerDepth=.12+this.density*1.18,halfHeight=Math.min(.24,layerDepth*.46)
      const height=2.42-halfHeight-(.5+.5*Math.sin(phase*1.7+seconds*.12))*(layerDepth-2*halfHeight)
      this.transform.position.set(Math.sin(phase+seconds*.035)*(this.width/2-radius)*.92,
        height,
        Math.cos(phase*1.3+seconds*.025)*(this.depth/2-radius)*.92)
      this.transform.scale.set(radius,halfHeight,radius)
      this.transform.updateMatrix();this.mesh.setMatrixAt(i,this.transform.matrix)
    }
    this.mesh.instanceMatrix.needsUpdate=true
  }
}
