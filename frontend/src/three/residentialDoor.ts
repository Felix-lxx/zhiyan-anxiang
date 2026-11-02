import * as THREE from 'three'
import type { SceneMaterials } from './sceneMaterials'
import { batchStaticParts } from './staticMeshBatch'

/** A residential door, not a certified fire-door assembly. Aperture remains frozen. */
export class ResidentialDoor {
  readonly frame=new THREE.Group()
  readonly leaf=new THREE.Group()
  readonly clearance:THREE.Mesh<THREE.BoxGeometry,THREE.MeshBasicMaterial>
  private target=0
  private initialized=false

  constructor(width:number,clearance:number,wallDepth:number,materials?:SceneMaterials){
    this.frame.name='residential-door';this.leaf.name='door-swing-leaf'
    const wood=materials?.surface('wood',0x9c8267,1,3)??new THREE.MeshStandardMaterial({color:0x9c8267,roughness:.68})
    const trim=new THREE.MeshStandardMaterial({color:0x77614e,roughness:.72})
    const steel=new THREE.MeshStandardMaterial({color:0x87908a,metalness:.7,roughness:.36})
    const seal=new THREE.MeshStandardMaterial({color:0x393e37,roughness:.95})
    function box(parent:THREE.Group,name:string,w:number,h:number,d:number,x:number,y:number,z:number,material:THREE.Material){
      const mesh=new THREE.Mesh(new THREE.BoxGeometry(w,h,d),material);mesh.name=name;mesh.position.set(x,y,z);mesh.castShadow=true;mesh.receiveShadow=true;parent.add(mesh);return mesh
    }
    for(const side of [-1,1]){
      box(this.frame,'door-jamb',.06,2.16,.12,side*(width/2+.03),1.08,0,trim)
      box(this.frame,'jamb-seal',.012,2.1,.015,side*(width/2+.006),1.05,-.035,seal)
    }
    box(this.frame,'door-lintel',width+.12,.08,.12,0,2.18,0,trim)
    box(this.frame,'sealed-transom',width+.12,.23,.1,0,2.335,0,materials?.surface('plaster',0xd9d9cf)??trim)
    // Park both handles beyond the clear aperture when the leaf is open.
    this.leaf.position.x=-width/2-.085;this.frame.add(this.leaf)
    const leafWidth=width+.08
    box(this.leaf,'door-leaf-panel',leafWidth,2.1,.045,leafWidth/2,1.05,0,wood)
    for(const side of [-1,1]){
      for(const y of [.58,1.47])box(this.leaf,'recessed-door-panel',Math.max(.1,leafWidth-.16),.68,.012,leafWidth/2,y,side*.027,trim)
      box(this.leaf,'handle-rosette',.055,.15,.018,leafWidth-.13,1.02,side*.041,steel)
      box(this.leaf,'door-lever',.13,.025,.025,leafWidth-.185,1.05,side*.068,steel)
    }
    for(const y of [.25,1.05,1.85]){
      const pin=new THREE.Mesh(new THREE.CylinderGeometry(.012,.012,.09,10),steel);pin.position.set(.012,y,0);this.leaf.add(pin)
    }
    this.clearance=new THREE.Mesh(new THREE.BoxGeometry(width+clearance*2,.008,wallDepth+clearance*2),new THREE.MeshBasicMaterial({color:0x6dc6ad,transparent:true,opacity:.26,depthWrite:false}))
    this.clearance.name='door-occupancy-envelope';this.clearance.position.y=.018;this.frame.add(this.clearance)
    batchStaticParts(this.leaf)
    batchStaticParts(this.frame,new Set(['door-occupancy-envelope']))
  }

  setOpen(open:boolean){
    this.target=open?Math.PI/2:0
    // Opening clears the confirmed walking route immediately; never delay passage.
    if(!this.initialized||open)this.leaf.rotation.y=this.target
    this.initialized=true
  }
  step(delta:number,animate:boolean){
    if(!animate){this.leaf.rotation.y=this.target;return}
    const change=this.target-this.leaf.rotation.y
    this.leaf.rotation.y+=Math.sign(change)*Math.min(Math.abs(change),Math.max(0,delta)*Math.PI*1.5)
  }
}
