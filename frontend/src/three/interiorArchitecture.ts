import * as THREE from 'three'
import type { SceneMaterials } from './sceneMaterials'

/** Back wall has an actual window opening; all panels keep their original footprint. */
export function kitchenWindowWall(width:number,depth:number,materials:SceneMaterials){
  const group=new THREE.Group(),height=2.45,z=-depth/2
  const windowWidth=Math.min(1.05,width*.23),center=-width*.103,bottom=1.15,windowHeight=.9
  const plaster=materials.surface('plaster',0xe3dfd2,width/2,1),metal=new THREE.MeshStandardMaterial({color:0x849a99,metalness:.5,roughness:.35})
  const glass=new THREE.MeshPhysicalMaterial({color:0xa9c4ce,roughness:.16,metalness:.05,transparent:true,opacity:.42,depthWrite:false,clearcoat:1})
  function panel(name:string,x:number,y:number,w:number,h:number,d:number,material:THREE.Material){const mesh=new THREE.Mesh(new THREE.BoxGeometry(w,h,d),material);mesh.name=name;mesh.position.set(x,y,z);mesh.castShadow=true;mesh.receiveShadow=true;group.add(mesh);return mesh}
  panel('window-wall-below',0,bottom/2,width,bottom,.08,plaster)
  panel('window-wall-above',0,(bottom+windowHeight+height)/2,width,height-bottom-windowHeight,.08,plaster)
  const left=center-windowWidth/2,right=center+windowWidth/2
  panel('window-wall-left',(-width/2+left)/2,bottom+windowHeight/2,left+width/2,windowHeight,.08,plaster)
  panel('window-wall-right',(width/2+right)/2,bottom+windowHeight/2,width/2-right,windowHeight,.08,plaster)
  for(const x of [left,right,center])panel('window-frame',x,bottom+windowHeight/2,.035,windowHeight,.08,metal)
  for(const y of [bottom,bottom+windowHeight])panel('window-frame',center,y,windowWidth+.035,.035,.08,metal)
  // Separate panes and seals give the opening depth without putting an opaque
  // wall behind the glass or projecting a handle into the walking area.
  const seal=new THREE.MeshStandardMaterial({color:0x354d4b,roughness:.8})
  for(const side of [-1,1]) {
    const paneX=center+side*windowWidth/4,paneWidth=windowWidth/2-.035
    panel('window-glass',paneX,bottom+windowHeight/2,paneWidth,windowHeight-.055,.012,glass)
    for(const edge of [-1,1])panel('window-seal',paneX+edge*paneWidth/2,bottom+windowHeight/2,.008,windowHeight-.04,.018,seal)
    const latch=panel('window-latch',center+side*.045,bottom+windowHeight*.48,.014,.11,.02,metal)
    latch.position.z+=.048
  }
  const sill=panel('window-sill',center,bottom-.025,windowWidth+.08,.05,.12,metal);sill.position.z+=.02
  panel('wall-skirt',0,.045,width,.09,.1,materials.surface('stone',0xaaa89e,width,1))
  return group
}
