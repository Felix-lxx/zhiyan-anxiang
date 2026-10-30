import * as THREE from 'three'
import type { IndoorState } from '../domain/indoor'
import { cutFloor, stairOpenings, furnitureFits, doorPortal, doorWallPanels, type Passage } from './indoorGeometry'
import { KitchenAssets } from './kitchenAssets'
import { SceneMaterials } from './sceneMaterials'

/** Rooms load by floor; all solids respect the frozen walking paths. */
export class IndoorFireVisuals {
  readonly group = new THREE.Group()
  private floors = new Map<number, THREE.Group>()
  private volumes = new Map<string, THREE.Mesh<THREE.BoxGeometry, THREE.MeshBasicMaterial>>()
  private doors = new Map<string, THREE.Group>()
  private doorFrames = new Map<string, THREE.Group>()
  private doorMarkers = new Map<string, THREE.Mesh<THREE.BoxGeometry, THREE.MeshBasicMaterial>>()
  private valves = new Map<string, {group:THREE.Group;handle:THREE.Mesh<THREE.BoxGeometry,THREE.MeshStandardMaterial>}>()
  private assets = new KitchenAssets()
  private closed = false
  private materials = new SceneMaterials()
  private roomObjects = new Map<string, THREE.Group>()
  private riskMarkers = new Map<string, THREE.Mesh<THREE.RingGeometry, THREE.MeshBasicMaterial>>()
  constructor(private initial: IndoorState, private point: (x: number, y: number, height: number) => THREE.Vector3,
    private register: (object: THREE.Object3D, data: Record<string, unknown>) => void, private passages: Passage[] = [], private invalidate: () => void = () => {}) {}

  private buildFloor(floor: number) {
    const layer = new THREE.Group(); this.group.add(layer); this.floors.set(floor, layer)
    const box = (parent: THREE.Group, w: number, h: number, d: number, color: number, x: number, y: number, z: number) => {
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), new THREE.MeshStandardMaterial({ color, roughness: .85 }))
      mesh.position.set(x, y, z); mesh.castShadow = true; mesh.receiveShadow = true; parent.add(mesh); return mesh
    }
    for (const zone of this.initial.zones.filter(zone => zone.floor === floor)) {
      const volume = new THREE.Mesh(new THREE.BoxGeometry(zone.width, .8, zone.depth),
        new THREE.MeshBasicMaterial({ color: 0xdab467, transparent: true, opacity: .02, depthWrite: false }))
      volume.position.copy(this.point(zone.x, zone.y, zone.height)).add(new THREE.Vector3(0, 2, 0))
      layer.add(volume); this.volumes.set(zone.id, volume)
      if (zone.kind === 'corridor') {
        const corridor = new THREE.Group(); corridor.position.copy(this.point(zone.x, zone.y, zone.height)); layer.add(corridor)
        for (const tile of cutFloor({x:zone.x,y:zone.y,width:zone.width,depth:zone.depth},stairOpenings(this.passages,zone.height))) {
          const slab=box(corridor,tile.width,.018,tile.depth,0xb9b7aa,tile.x-zone.x,.009,tile.y-zone.y)
          slab.material.dispose(); slab.material=this.materials.surface('tile',0xc8c7bd,tile.width/.7,tile.depth/.7)
        }
        continue
      }
      if (zone.kind !== 'room') continue
      const kitchen = new THREE.Group(); kitchen.position.copy(this.point(zone.x, zone.y, zone.height)); layer.add(kitchen)
      this.roomObjects.set(zone.id, kitchen)
      for(const tile of cutFloor({x:zone.x,y:zone.y,width:zone.width,depth:zone.depth},stairOpenings(this.passages,zone.height))) {
        const slab=box(kitchen,tile.width,.015,tile.depth,0xc3bda9,tile.x-zone.x,.008,tile.y-zone.y)
        slab.material.dispose(); slab.material=this.materials.surface('tile',0xe5e1d3,tile.width/.6,tile.depth/.6)
      }
      const back={x:zone.x,y:zone.y-zone.depth/2,width:zone.width,depth:.08}
      if(furnitureFits(back,zone.height,this.passages)) {
        box(kitchen,zone.width,2.2,.08,0xd7d2bf,0,1.1,-zone.depth/2)
        const splash=box(kitchen,zone.width-.12,.6,.025,0xffffff,0,1.23,-zone.depth/2+.055)
        splash.material.dispose(); splash.material=this.materials.surface('tile',0xe4e5da,zone.width/.3,2)
        box(kitchen,zone.width,.09,.04,0x7b8275,0,.06,-zone.depth/2+.06)
      }
      for (const side of [-1,1]) {
        const wall={x:zone.x+side*zone.width/2,y:zone.y,width:.08,depth:zone.depth}
        if(furnitureFits(wall,zone.height,this.passages)) {
          box(kitchen,.08,2.2,zone.depth,0xc9c9bb,side*zone.width/2,1.1,0)
          box(kitchen,.045,.09,zone.depth-.08,0x727b70,side*(zone.width/2-.05),.065,0)
        }
      }
      // Small historical rooms may have no safe cabinet footprint. Keep their
      // selectable marker, never fill the residents' route with decorative furniture.
      const layout = this.initial.equipment_layouts?.find(item => item.room_id === zone.id)
      const counter = layout?.counter ?? { x: zone.x, y: zone.y - zone.depth * .38, width: zone.width * .82, depth: zone.depth * .2 }
      if ((!this.initial.equipment_layout_version || layout) && furnitureFits(counter, zone.height, this.passages)) {
        const z = counter.y - zone.y, d = counter.depth, w = counter.width
        const stoveX = layout ? layout.stove.position.x - zone.x : w * .375
        const top = layout?.stove.height ?? .92
        const fallback = new THREE.Group(); kitchen.add(fallback)
        const original = kitchen.children.length
        box(kitchen, w, .85, d, 0x879b8b, 0, .43, z)
        box(kitchen, w, .07, d, 0xddd6bf, 0, .875, z)
        box(kitchen, w / 4 - .04, .02, d * .9, 0x283635, stoveX, top - .01, z)
        for (const side of [-1, 1]) {
          const burner = new THREE.Mesh(new THREE.TorusGeometry(Math.min(.08, d * .2, w / 32), .012, 5, 12), new THREE.MeshStandardMaterial({ color: 0x172321 }))
          burner.rotation.x = Math.PI / 2; burner.position.set(stoveX + side * w / 16, top, z); kitchen.add(burner)
        }
        for (let i = 0; i < 3; i++) box(kitchen, Math.min(.18,w/6), .025, .025, 0x344e46, (i - 1) * w / 3, .72, z + d / 2 - .02)
        // Preserve the usable fallback until every local asset has loaded.
        for (const child of kitchen.children.slice(original)) fallback.add(child)
        const unit = w / 4
        // These architectural fittings survive the fallback-to-GLB swap.
        // Keep their complete extents inside the same frozen countertop envelope.
        box(kitchen,w,.08,d*.8,0x344e46,0,.04,z)
        for(const x of [0,unit]) box(kitchen,.035,top,d,0x879b8b,x,top/2,z)
        const hood=box(kitchen,unit-.04,.12,d*.85,0x65716e,stoveX,1.85,z)
        hood.material.metalness=.65;hood.material.roughness=.4
        box(kitchen,Math.min(.24,unit*.3),.19,d*.4,0x89918b,stoveX,2.005,z-d*.2)
        const filter=box(kitchen,unit*.7,.012,d*.6,0x293d37,stoveX,1.783,z)
        filter.material.metalness=.5
        box(kitchen,unit*.65,.025,.04,0xdad8b8,stoveX,1.78,z+d*.3)
        void Promise.all(['kitchenFridge', 'kitchenSink', 'kitchenCabinetDrawer', 'kitchenStove'].map((name, index) =>
          // Shipped Kenney cabinets share a local y=.45 worktop; the sink's
          // faucet reaches .49. Align the worktop, never the faucet's bounds.
          this.assets.fit(name, unit - .04, index === 0 ? 1.85 : top*(index===1?.49/.45:1), d, index===0?undefined:.45).then(model => {
            if (model) {
              model.position.set(index === 3 ? stoveX : (index - 1.5) * unit, 0, z)
              if (index > 0) {
                const lift = Math.max(0, top - Number(model.userData.worktopHeight))
                model.position.y = lift
                if (lift > .005) box(model, unit - .04, lift, d, 0x879b8b, 0, -lift / 2, 0)
              }
            }
            return model
          }))).then(models => {
          if (this.closed || models.some(model => !model)) return
          fallback.visible = false
          for (const model of models) {
            kitchen.add(model!)
            model!.traverse(child => { child.userData.selection = kitchen.userData.selection })
          }
          this.invalidate()
        }).catch(() => { fallback.visible = true })
        void this.assets.fit('kitchenCabinetUpper', unit * 1.8, .55, d * .65).then(model => {
          if (!model || this.closed) return
          model.position.set(0, 1.55, z - d * .16); kitchen.add(model)
          model.traverse(child => { child.userData.selection = kitchen.userData.selection })
          this.invalidate()
        }).catch(() => {})
      }
      const marker = new THREE.Mesh(new THREE.RingGeometry(.35, .43, 24), new THREE.MeshBasicMaterial({ color: 0xc5cbb8, side: THREE.DoubleSide }))
      marker.rotation.x = -Math.PI / 2; marker.position.y = .015; kitchen.add(marker)
      this.riskMarkers.set(zone.id, marker)
      const canvas=document.createElement('canvas');canvas.width=256;canvas.height=64
      const context=canvas.getContext('2d')!
      context.fillStyle='#17352b';context.fillRect(0,0,256,64);context.fillStyle='#f4f4df';context.font='500 26px "Microsoft YaHei",sans-serif';context.textAlign='center';context.textBaseline='middle'
      context.fillText(`${zone.floor}层 · ${zone.id.endsWith(':east')?'东侧':'西侧'}厨房`,128,32)
      const label=new THREE.Sprite(new THREE.SpriteMaterial({map:new THREE.CanvasTexture(canvas),depthTest:true}))
      label.position.set(0,2.4,-zone.depth*.3);label.scale.set(Math.min(3,zone.width),Math.min(3,zone.width)/4,1);kitchen.add(label)
      this.register(kitchen, { title: zone.name, type: '厨房房间', detail: '房门、人员路径与分区烟气使用同一空间节点。',
        fireRoom: { floor: zone.floor, room: zone.id.endsWith(':east') ? 'east' : 'west' }, x: zone.x, y: zone.y })
      if (layout?.gas_valve && furnitureFits(counter, zone.height, this.passages)) {
        const device=layout.gas_valve, valve=new THREE.Group()
        valve.position.copy(this.point(device.position.x,device.position.y,device.position.height));layer.add(valve)
        const pipe=new THREE.Mesh(new THREE.CylinderGeometry(.025,.025,.86,10),new THREE.MeshStandardMaterial({color:0xb69a67,roughness:.45,metalness:.55}))
        valve.add(pipe)
        const handle=box(valve,.055,.26,.045,0xe6b865,0,0,.065)
        this.valves.set(device.id,{group:valve,handle})
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
        const wall=box(layer,panel.width,2.2,panel.depth,0xc9c9bb,0,0,0)
        wall.position.copy(this.point(panel.x,panel.y,room.height)); wall.position.y+=1.1
        const cap=box(layer,panel.width+.015,.035,panel.depth+.015,0xe0dac9,0,0,0)
        cap.position.copy(this.point(panel.x,panel.y,room.height));cap.position.y+=2.2175
      }
      const frame = new THREE.Group(); frame.position.copy(this.point(opening.x, opening.y, room.height))
      frame.rotation.y = opening.rotation; layer.add(frame)
      for (const side of [-1, 1]) box(frame, .06, 2.14, .1, 0x8b7257, side * (width / 2 + .03), 1.07, 0)
      box(frame, width + .12, .08, .1, 0x8b7257, 0, 2.18, 0)
      const hinge = new THREE.Group(); hinge.position.x = opening.hingeX; frame.add(hinge)
      box(hinge, width, 2.1, .045, 0xb89467, width / 2, 1.05, 0)
      box(hinge, .035, .12, .08, 0x344e46, width - .12, 1, -.05)
      this.doors.set(door.id, hinge)
      const clearance=door.portal?.clearance_radius??0
      const marker=new THREE.Mesh(new THREE.BoxGeometry(width+2*clearance,.015,(door.portal?.wall_depth??.22)+2*clearance),new THREE.MeshBasicMaterial({color:0x6dc6ad,transparent:true,opacity:.32,depthWrite:false}))
      marker.position.y=.018;frame.add(marker);this.doorMarkers.set(door.id,marker);this.doorFrames.set(door.id,frame)
      this.register(frame, {title:door.label,type:'可操作房门',action:'indoor-door',doorId:door.id,detail:'点击查看本扇房门、占用人员与通行条件。',x:opening.x,y:opening.y})
    }
  }

  update(state: IndoorState, floor?: number) {
    const selected = floor ?? state.zones.find(zone => zone.id === state.source_zone_id)?.floor ?? 1
    if (!this.floors.has(selected)) this.buildFloor(selected)
    for (const [level, group] of this.floors) group.visible = level === selected
    for (const zone of state.zones) {
      const mesh = this.volumes.get(zone.id)
      if (mesh) { mesh.visible = zone.smoke_density > .005; mesh.material.opacity = Math.min(.45, zone.smoke_density * .55); mesh.material.color.setHex(zone.smoke_density > .55 ? 0x6f5145 : 0xb39b70) }
      const marker = this.riskMarkers.get(zone.id)
      if (marker) marker.material.color.setHex(zone.id === state.source_zone_id ? 0xf06a43 : zone.smoke_density > .3 ? 0xe6b865 : 0x6dc6ad)
      const room = this.roomObjects.get(zone.id)
      if (room?.userData.selection) room.userData.selection.detail = `${zone.id === state.source_zone_id ? '本场起火房间 · ' : ''}烟气 ${Math.round(zone.smoke_density * 100)}% · ${zone.temperature} ℃ · 可见度指数 ${zone.visibility}%`
    }
    for (const door of state.doors) {
      const hinge = this.doors.get(door.id)
      if (hinge) hinge.rotation.y = door.state === 'open' ? Math.PI / 2 : 0
      const marker=this.doorMarkers.get(door.id)
      if(marker)marker.material.color.setHex(door.state==='closed'?0xf06a43:door.can_close===false?0xe6b865:0x6dc6ad)
      const frame=this.doorFrames.get(door.id)
      if(frame?.userData.selection)frame.userData.selection.detail=door.state==='closed'?'房门关闭，当前通道不可通行。':door.can_close===false?`${door.occupants?.length??0} 人仍在房内或通过房门，暂不能关闭。`:'房门打开，人员可通行。点击查看门控与占用情况。'
    }
    for (const device of state.devices??[]) {
      const valve=this.valves.get(device.id)
      if(!valve)continue
      const closed=device.state==='closed'
      valve.handle.rotation.z=closed?Math.PI/2:0
      valve.handle.material.color.setHex(closed?0x6dc6ad:0xe6b865)
      if(valve.group.userData.selection)valve.group.userData.selection.detail=closed?'关闭 · 处置证据已核验。点击查看任务记录。':'打开 · 尚未核验关闭。点击进入处置任务。'
    }
  }

  dispose() { this.closed = true; this.assets.dispose(); this.materials.dispose() }
}
