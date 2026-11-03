import * as THREE from 'three'
import type {IndoorZone,IndoorDoor} from '../domain/indoor'

/** A readable projection of confirmed zone state; no local fire simulation. */
export function zoneSignState(zone:IndoorZone,door:IndoorDoor|undefined,source:boolean){
  const percent=Math.round(THREE.MathUtils.clamp(zone.smoke_density,0,1)*100)
  const room=zone.id?.endsWith(':east')?`${zone.floor}层东侧厨房`:zone.id?.endsWith(':west')?`${zone.floor}层西侧厨房`:zone.name
  return {
    title:`${source?'起火房间 · ':''}${room}`,
    environment:`烟气 ${percent}% · ${Math.round(zone.temperature)} ℃`,
    passage:door?door.state==='closed'?'房门关闭':door.can_close===false?'房门开启 · 暂不能关闭':door.can_close===true?'房门开启 · 可关门':'房门开启 · 占用待核对':'房门状态未提供',
    color:source?'#f2b79a':percent>30?'#f2d18b':'#c8e5d7',
  }
}

export class IndoorZoneSign {
  readonly sprite:THREE.Sprite
  private canvas=document.createElement('canvas')
  private texture:THREE.CanvasTexture
  private signature=''
  constructor(width:number){
    this.canvas.width=512;this.canvas.height=176
    this.texture=new THREE.CanvasTexture(this.canvas)
    this.texture.colorSpace=THREE.SRGBColorSpace
    this.sprite=new THREE.Sprite(new THREE.SpriteMaterial({map:this.texture,depthTest:true}))
    this.sprite.name='room-confirmed-state-sign'
    const size=Math.min(4.6,Math.max(1.1,width*.9))
    this.sprite.scale.set(size,size*176/512,1)
  }
  update(zone:IndoorZone,door:IndoorDoor|undefined,source:boolean){
    const state=zoneSignState(zone,door,source),signature=JSON.stringify(state)
    if(signature===this.signature)return
    this.signature=signature
    this.sprite.userData.zoneState=state
    const context=this.canvas.getContext('2d')!
    context.fillStyle='#132f27';context.fillRect(0,0,512,176)
    const line=(text:string,y:number,size:number,color:string)=>{
      context.font=`500 ${size}px "Microsoft YaHei",sans-serif`
      while(context.measureText(text).width>480&&size>20){size--;context.font=`500 ${size}px "Microsoft YaHei",sans-serif`}
      context.fillStyle=color;context.textAlign='left';context.textBaseline='middle';context.fillText(text,16,y,480)
    }
    line(state.title,30,32,state.color)
    line(state.environment,88,36,'#f1f5e9')
    line(state.passage,146,32,'#c8ded2')
    this.texture.needsUpdate=true
  }
}
