import * as THREE from 'three'
import type { BuildingReleaseSignal } from '../domain/agent'

export const releaseLabels:Record<string,string>={waiting:'等待放行',executing:'正在撤离',blocked:'放行受阻',stopped:'等待人工安排',completed:'已到集合点'}
const colors:Record<string,string>={waiting:'#ffd18a',executing:'#8ce9e0',blocked:'#ffad96',stopped:'#ffd18a',completed:'#a3ebbd'}
interface Building {id:string;x:number;y:number;floors:number;entry:{x:number;y:number}}
interface Marker {group:THREE.Group;label:THREE.Sprite;ring:THREE.Mesh;signature:string}

/** Annotation geometry only: never changes a doorway, collision or release rule. */
export class BuildingReleaseVisuals {
  readonly layer=new THREE.Group()
  private markers=new Map<string,Marker>()
  sync(signals:BuildingReleaseSignal[],buildings:Building[]){
    const wanted=new Set(signals.map(signal=>signal.id))
    for(const [id,marker] of this.markers)if(!wanted.has(id)){this.remove(marker);this.markers.delete(id)}
    for(const signal of signals){
      const building=buildings.find(item=>item.id===signal.id)
      if(!building)continue
      let marker=this.markers.get(signal.id)
      if(!marker){
        const group=new THREE.Group()
        const label=new THREE.Sprite(new THREE.SpriteMaterial({transparent:true,depthTest:true}))
        const ring=new THREE.Mesh(new THREE.RingGeometry(1.15,1.32,40),new THREE.MeshBasicMaterial({transparent:true,opacity:.85,side:THREE.DoubleSide,depthWrite:false}))
        ring.rotation.x=-Math.PI/2;group.add(label,ring);this.layer.add(group)
        marker={group,label,ring,signature:''};this.markers.set(signal.id,marker)
      }
      marker.label.position.set(building.x-50,building.floors*3.2+3.8,building.y-50)
      marker.ring.position.set(building.entry.x-50,.12,building.entry.y-50)
      const signature=JSON.stringify([signal.name,signal.state,signal.arrived,signal.total,signal.wave])
      if(marker.signature===signature)continue
      marker.signature=signature
      const canvas=document.createElement('canvas');canvas.width=640;canvas.height=168
      const ctx=canvas.getContext('2d')!
      ctx.fillStyle='#09291f';ctx.fillRect(0,0,640,168)
      ctx.strokeStyle=colors[signal.state]??'#d5e6dc';ctx.lineWidth=3;ctx.strokeRect(2,2,636,164)
      ctx.font='600 52px sans-serif';ctx.fillStyle='#eff8f2'
      ctx.fillText(signal.name,22,62,596)
      ctx.font='48px sans-serif';ctx.fillStyle=ctx.strokeStyle
      ctx.fillText(`${releaseLabels[signal.state]??'待核对'} · 到场 ${signal.arrived}/${signal.total}`,22,136,596)
      const material=marker.label.material as THREE.SpriteMaterial
      material.map?.dispose();material.map=new THREE.CanvasTexture(canvas);material.map.colorSpace=THREE.SRGBColorSpace;material.needsUpdate=true
      ;(marker.ring.material as THREE.MeshBasicMaterial).color.set(colors[signal.state]??'#d5e6dc')
    }
  }
  step(camera:THREE.Camera,visible:boolean){
    this.layer.visible=visible
    if(!visible)return
    const occupied:Array<{left:number;right:number;top:number;bottom:number}>=[]
    for(const marker of this.markers.values()){
      const width=marker.label.position.distanceTo(camera.position)*.34
      marker.label.scale.set(width,width*168/640,1)
      const view=marker.label.position.clone().applyMatrix4(camera.matrixWorldInverse)
      const point=marker.label.position.clone().project(camera)
      const halfX=width*camera.projectionMatrix.elements[0]!/Math.max(.01,-view.z)/2
      const halfY=width*168/640*camera.projectionMatrix.elements[5]!/Math.max(.01,-view.z)/2
      const box={left:point.x-halfX-.015,right:point.x+halfX+.015,top:point.y+halfY+.015,bottom:point.y-halfY-.015}
      marker.label.visible=view.z<0&&Math.abs(point.z)<=1&&!occupied.some(other=>box.left<other.right&&box.right>other.left&&box.bottom<other.top&&box.top>other.bottom)
      if(marker.label.visible)occupied.push(box)
    }
  }
  private remove(marker:Marker){
    this.layer.remove(marker.group)
    const material=marker.label.material as THREE.SpriteMaterial
    material.map?.dispose();material.dispose();marker.ring.geometry.dispose();(marker.ring.material as THREE.Material).dispose()
  }
  dispose(){for(const marker of this.markers.values())this.remove(marker);this.markers.clear()}
}
