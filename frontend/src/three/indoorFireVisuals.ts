import * as THREE from 'three'
import type { IndoorState } from '../domain/indoor'
import { cutFloor, stairOpenings, furnitureFits, doorPortal, doorWallPanels, type Passage } from './indoorGeometry'
import { createKitchenAssembly } from './kitchenAssembly'
import { kitchenWindowWall } from './interiorArchitecture'
import { createGasValve, type GasValveVisual } from './gasValve'
import { ResidentialDoor } from './residentialDoor'
import { IndoorSmoke } from './indoorSmoke'
import { IndoorZoneSign } from './indoorZoneSign'
import { SceneMaterials } from './sceneMaterials'

/** Rooms load by floor; all solids respect the frozen walking paths. */
export class IndoorFireVisuals {
  readonly group = new THREE.Group()
  private floors = new Map<number, THREE.Group>()
  private volumes = new Map<string, IndoorSmoke>()
  private cutawayWalls:Array<{object:THREE.Object3D;center:THREE.Vector3;normalX:number;normalZ:number}> = []
  private labels = new Set<THREE.Sprite>()
  private roomSigns = new Map<string,IndoorZoneSign>()
  private doors = new Map<string, ResidentialDoor>()
  private doorFrames = new Map<string, THREE.Group>()
  private valves = new Map<string, GasValveVisual>()
  private materials = new SceneMaterials()
  private roomObjects = new Map<string, THREE.Group>()
  private riskMarkers = new Map<string, THREE.Mesh<THREE.RingGeometry, THREE.MeshBasicMaterial>>()
  constructor(private initial: IndoorState, private point: (x: number, y: number, height: number) => THREE.Vector3,
    private register: (object: THREE.Object3D, data: Record<string, unknown>) => void, private passages: Passage[] = []) {}

  private buildFloor(floor: number) {
    const layer = new THREE.Group(); this.group.add(layer); this.floors.set(floor, layer)
    const box = (parent: THREE.Group, w: number, h: number, d: number, color: number, x: number, y: number, z: number) => {
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), new THREE.MeshStandardMaterial({ color, roughness: .85 }))
      mesh.position.set(x, y, z); mesh.castShadow = true; mesh.receiveShadow = true; parent.add(mesh); return mesh
    }
    for (const zone of this.initial.zones.filter(zone => zone.floor === floor)) {
      const smoke = new IndoorSmoke(zone.width,zone.depth,floor*17+this.volumes.size)
      smoke.mesh.position.copy(this.point(zone.x,zone.y,zone.height));layer.add(smoke.mesh);this.volumes.set(zone.id,smoke)
      if (zone.kind === 'corridor') {
        const corridor = new THREE.Group(); corridor.position.copy(this.point(zone.x, zone.y, zone.height)); layer.add(corridor)
        for (const tile of cutFloor({x:zone.x,y:zone.y,width:zone.width,depth:zone.depth},stairOpenings(this.passages,zone.height))) {
          const slab=box(corridor,tile.width,.018,tile.depth,0xb9b7aa,tile.x-zone.x,-.009,tile.y-zone.y)
          slab.material.dispose(); slab.material=this.materials.surface('tile',0xc8c7bd,tile.width/.7,tile.depth/.7)
        }
        continue
      }
      if (zone.kind !== 'room') continue
      const kitchen = new THREE.Group(); kitchen.position.copy(this.point(zone.x, zone.y, zone.height)); layer.add(kitchen)
      this.roomObjects.set(zone.id, kitchen)
      for(const tile of cutFloor({x:zone.x,y:zone.y,width:zone.width,depth:zone.depth},stairOpenings(this.passages,zone.height))) {
        const slab=box(kitchen,tile.width,.015,tile.depth,0xc3bda9,tile.x-zone.x,-.0075,tile.y-zone.y)
        slab.material.dispose(); slab.material=this.materials.surface('tile',0xe5e1d3,tile.width/.6,tile.depth/.6)
      }
      const back={x:zone.x,y:zone.y-zone.depth/2,width:zone.width,depth:.08}
      if(furnitureFits(back,zone.height,this.passages)) {
        kitchen.add(kitchenWindowWall(zone.width,zone.depth,this.materials))
      }
      for (const side of [-1,1]) {
        const wall={x:zone.x+side*zone.width/2,y:zone.y,width:.08,depth:zone.depth}
        if(furnitureFits(wall,zone.height,this.passages)) {
          const wall=box(kitchen,.08,2.45,zone.depth,0xd5d6cf,side*zone.width/2,1.225,0)
          wall.material.dispose();wall.material=this.materials.surface('plaster',0xd9d9cf,1,zone.depth/2)
          this.cutawayWalls.push({object:wall,center:this.point(zone.x,zone.y,zone.height),normalX:side,normalZ:0})
          box(kitchen,.045,.09,zone.depth-.08,0x727b70,side*(zone.width/2-.05),.065,0)
        }
      }
      // Small historical rooms may have no safe cabinet footprint. Keep their
      // selectable marker, never fill the residents' route with decorative furniture.
      const layout = this.initial.equipment_layouts?.find(item => item.room_id === zone.id)
      const counter = layout?.counter ?? { x: zone.x, y: zone.y - zone.depth * .38, width: zone.width * .82, depth: zone.depth * .2 }
      if ((!this.initial.equipment_layout_version || layout) && furnitureFits(counter, zone.height, this.passages)) {
        const stoveX=layout?layout.stove.position.x-counter.x:counter.width*.375
        const assembly=createKitchenAssembly({width:counter.width,depth:counter.depth,worktopHeight:layout?.stove.height??.92,stoveX},this.materials)
        assembly.position.set(counter.x-zone.x,0,counter.y-zone.y);kitchen.add(assembly)
      }
      // The ceiling is removed for inspection: mount the luminaire on the
      // retained back wall so its housing never appears suspended in mid-air.
      if (furnitureFits(back,zone.height,this.passages)) {
        box(kitchen,.38,.18,.065,0x778781,0,2.27,-zone.depth/2+.065)
        const lamp=new THREE.Mesh(new THREE.BoxGeometry(.32,.115,.018),new THREE.MeshStandardMaterial({color:0xf4efd9,emissive:0xffe5b5,emissiveIntensity:1.2}))
        lamp.name='wall-mounted-kitchen-light';lamp.position.set(0,2.27,-zone.depth/2+.108);kitchen.add(lamp)
        const light=new THREE.PointLight(0xffe4b4,5,8,2);light.position.set(0,2.18,-zone.depth/2+.3);light.userData.indoor=true;kitchen.add(light)
      }
      const marker = new THREE.Mesh(new THREE.RingGeometry(.35, .43, 24), new THREE.MeshBasicMaterial({ color: 0xc5cbb8, side: THREE.DoubleSide }))
      marker.rotation.x = -Math.PI / 2; marker.position.y = .015; kitchen.add(marker)
      this.riskMarkers.set(zone.id, marker)
      const sign=new IndoorZoneSign(zone.width),label=sign.sprite
      // Keep the entire annotation above the 2.45 m wall, not intersecting it.
      label.position.set(0,2.53+label.scale.y/2,-zone.depth*.3);kitchen.add(label);this.labels.add(label);this.roomSigns.set(zone.id,sign)
      this.register(kitchen, { title: zone.name, type: '厨房房间', detail: '房门、人员路径与分区烟气使用同一空间节点。',
        fireRoom: { floor: zone.floor, room: zone.id.endsWith(':east') ? 'east' : 'west' }, x: zone.x, y: zone.y })
      if (layout?.gas_valve && furnitureFits(counter, zone.height, this.passages)) {
        const device=layout.gas_valve,hardware=createGasValve(counter.depth),valve=hardware.group
        valve.position.copy(this.point(device.position.x,device.position.y,device.position.height));layer.add(valve)
        this.valves.set(device.id,hardware)
        this.register(valve,{title:device.label,type:'燃气阀',action:'indoor-device',deviceId:device.id,
          detail:'打开 · 关闭状态需由处置任务证据核验。',x:device.position.x,y:device.position.y,
          fireRoom:{floor:zone.floor,room:zone.id.endsWith(':east')?'east':'west'}})
      }
    }
    for (const door of this.initial.doors.filter(door => door.floor === floor)) {
      const room = this.initial.zones.find(zone => zone.id === door.room_id)
      const passage = this.passages.find(edge => edge.id === door.id)
      const hall = passage?.end ?? this.initial.zones.find(zone => zone.kind === 'corridor' && zone.floor === floor)
      if (!room || !hall) continue
      const legacy = doorPortal(room, hall, passage?.width_meters ?? .9)
      const opening = door.portal ? {...legacy, x:door.portal.x, y:door.portal.y,
        width:door.portal.width, rotation:Math.atan2(door.portal.normal_x,door.portal.normal_y),
        hingeX:-door.portal.width/2-.04} : legacy
      const width = opening.width
      for (const panel of doorWallPanels(room, opening)) {
        if (!furnitureFits(panel, room.height, this.passages)) continue
        const wall=box(layer,panel.width,2.45,panel.depth,0xc9c9bb,0,0,0)
        wall.position.copy(this.point(panel.x,panel.y,room.height)); wall.position.y+=1.225
        const cap=box(layer,panel.width+.015,.035,panel.depth+.015,0xe0dac9,0,0,0)
        cap.position.copy(this.point(panel.x,panel.y,room.height));cap.position.y+=2.4675
        const center=this.point(room.x,room.y,room.height)
        for(const object of [wall,cap])this.cutawayWalls.push({object,center,normalX:Math.sin(opening.rotation),normalZ:Math.cos(opening.rotation)})
      }
      const visual=new ResidentialDoor(width,door.portal?.clearance_radius??0,door.portal?.wall_depth??.22,this.materials)
      const frame=visual.frame;frame.position.copy(this.point(opening.x,opening.y,room.height));frame.rotation.y=opening.rotation;layer.add(frame)
      this.doors.set(door.id,visual);this.doorFrames.set(door.id,frame)
      this.register(frame, {title:door.label,type:'可操作房门',action:'indoor-door',doorId:door.id,detail:'点击查看本扇房门、占用人员与通行条件。',x:opening.x,y:opening.y})
    }
  }

  update(state: IndoorState, floor?: number) {
    const selected = floor ?? state.zones.find(zone => zone.id === state.source_zone_id)?.floor ?? 1
    if (!this.floors.has(selected)) this.buildFloor(selected)
    for (const [level, group] of this.floors) group.visible = level === selected
    const doorsByRoom=new Map(state.doors.map(door=>[door.room_id,door]))
    for (const zone of state.zones) {
      this.roomSigns.get(zone.id)?.update(zone,doorsByRoom.get(zone.id),zone.id===state.source_zone_id)
      this.volumes.get(zone.id)?.update(zone.smoke_density,zone.temperature)
      const marker = this.riskMarkers.get(zone.id)
      if (marker) marker.material.color.setHex(zone.id === state.source_zone_id ? 0xf06a43 : zone.smoke_density > .3 ? 0xe6b865 : 0x6dc6ad)
      const room = this.roomObjects.get(zone.id)
      if (room?.userData.selection) room.userData.selection.detail = `${zone.id === state.source_zone_id ? '本场起火房间 · ' : ''}烟气 ${Math.round(zone.smoke_density * 100)}% · ${zone.temperature} ℃ · 可见度指数 ${zone.visibility}%`
    }
    for (const door of state.doors) {
      this.doors.get(door.id)?.setOpen(door.state==='open')
      this.doors.get(door.id)?.setOccupied(door.can_close===false||Boolean(door.occupants?.length))
      const frame=this.doorFrames.get(door.id)
      if(frame?.userData.selection)frame.userData.selection.detail=door.state==='closed'?'房门关闭，当前通道不可通行。':door.can_close===false?`${door.occupants?.length??0} 人仍在房内或通过房门，暂不能关闭。`:'房门打开，人员可通行。点击查看门控与占用情况。'
    }
    for (const device of state.devices??[]) {
      const valve=this.valves.get(device.id)
      if(!valve)continue
      const closed=device.state==='closed'
      valve.setClosed(closed)
      if(valve.group.userData.selection)valve.group.userData.selection.detail=closed?'关闭 · 处置证据已核验。点击查看任务记录。':'打开 · 尚未核验关闭。点击进入处置任务。'
    }
  }

  step(seconds:number,camera:THREE.Camera,quality=1,detailed=false,delta=0,animate=false){
    for(const door of this.doors.values())door.step(delta,animate)
    for(const valve of this.valves.values())valve.step(delta,animate)
    for(const label of this.labels)label.visible=!detailed
    for(const smoke of this.volumes.values())if(smoke.mesh.parent?.visible)smoke.step(seconds,quality)
    for(const wall of this.cutawayWalls)wall.object.visible=!(camera.position.y>wall.center.y+2.5&&(camera.position.x-wall.center.x)*wall.normalX+(camera.position.z-wall.center.z)*wall.normalZ>.4)
  }

  settleTransitions(){for(const door of this.doors.values())door.step(0,false);for(const valve of this.valves.values())valve.step(0,false)}

  dispose() { this.materials.dispose() }
}
