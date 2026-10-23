import * as THREE from 'three'
import type { IndoorState, IndoorZone } from '../domain/indoor'
import { cutFloor, stairOpenings, furnitureFits, type Passage } from './indoorGeometry'

/** Rooms load by floor; all solids respect the frozen walking paths. */
export class IndoorFireVisuals {
  readonly group = new THREE.Group()
  private floors = new Map<number, THREE.Group>()
  private volumes = new Map<string, THREE.Mesh<THREE.BoxGeometry, THREE.MeshBasicMaterial>>()
  private doors = new Map<string, THREE.Group>()
  constructor(private initial: IndoorState, private point: (x: number, y: number, height: number) => THREE.Vector3,
    private register: (object: THREE.Object3D, data: Record<string, unknown>) => void, private passages: Passage[] = []) {}

  private buildFloor(floor: number) {
    const layer = new THREE.Group(); this.group.add(layer); this.floors.set(floor, layer)
    const box = (parent: THREE.Group, w: number, h: number, d: number, color: number, x: number, y: number, z: number) => {
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), new THREE.MeshStandardMaterial({ color, roughness: .85 }))
      mesh.position.set(x, y, z); mesh.castShadow = true; mesh.receiveShadow = true; parent.add(mesh); return mesh
    }
    for (const zone of this.initial.zones.filter(zone => zone.floor === floor)) {
      const volume = new THREE.Mesh(new THREE.BoxGeometry(zone.width, 2.1, zone.depth),
        new THREE.MeshBasicMaterial({ color: 0xdab467, transparent: true, opacity: .02, depthWrite: false }))
      volume.position.copy(this.point(zone.x, zone.y, zone.height)).add(new THREE.Vector3(0, 1.35, 0))
      layer.add(volume); this.volumes.set(zone.id, volume)
      if (zone.kind !== 'room') continue
      const kitchen = new THREE.Group(); kitchen.position.copy(this.point(zone.x, zone.y, zone.height)); layer.add(kitchen)
      for(const tile of cutFloor({x:zone.x,y:zone.y,width:zone.width,depth:zone.depth},stairOpenings(this.passages,zone.height)))
        box(kitchen,tile.width,.015,tile.depth,0xc3bda9,tile.x-zone.x,.008,tile.y-zone.y)
      const back={x:zone.x,y:zone.y-zone.depth/2,width:zone.width,depth:.08}
      if(furnitureFits(back,zone.height,this.passages))box(kitchen,zone.width,2.2,.08,0xd7d2bf,0,1.1,-zone.depth/2)
      // Small historical rooms may have no safe cabinet footprint. Keep their
      // selectable marker, never fill the residents' route with decorative furniture.
      const counter = { x: zone.x, y: zone.y - zone.depth * .38, width: zone.width * .82, depth: zone.depth * .2 }
      if (furnitureFits(counter, zone.height, this.passages)) {
        const z = counter.y - zone.y, d = counter.depth, w = counter.width
        box(kitchen, w, .85, d, 0x879b8b, 0, .43, z)
        box(kitchen, w + .04, .07, d + .04, 0xddd6bf, 0, .89, z)
        box(kitchen, Math.min(.7, w * .4), .06, d * .9, 0x283635, w * .22, .95, z)
        box(kitchen, Math.min(.8, w * .46), .14, d, 0x596765, w * .22, 2, z)
        for (const side of [-1, 1]) {
          const burner = new THREE.Mesh(new THREE.TorusGeometry(Math.min(.1, d * .3), .018, 5, 12), new THREE.MeshStandardMaterial({ color: 0x172321 }))
          burner.rotation.x = Math.PI / 2; burner.position.set(w * .22 + side * .11, 1, z); kitchen.add(burner)
        }
        for (let i = 0; i < 3; i++) box(kitchen, .18, .025, .025, 0x344e46, (i - 1) * w / 3, .72, z + d / 2 + .025)
      }
      const marker = new THREE.Mesh(new THREE.RingGeometry(.35, .43, 24), new THREE.MeshBasicMaterial({ color: 0xc5cbb8, side: THREE.DoubleSide }))
      marker.rotation.x = -Math.PI / 2; marker.position.y = .015; kitchen.add(marker)
      const canvas=document.createElement('canvas');canvas.width=256;canvas.height=64
      const context=canvas.getContext('2d')!
      context.fillStyle='#17352b';context.fillRect(0,0,256,64);context.fillStyle='#f4f4df';context.font='500 26px "Microsoft YaHei",sans-serif';context.textAlign='center';context.textBaseline='middle'
      context.fillText(`${zone.floor}层 · ${zone.id.endsWith(':east')?'东侧':'西侧'}厨房`,128,32)
      const label=new THREE.Sprite(new THREE.SpriteMaterial({map:new THREE.CanvasTexture(canvas),depthTest:true}))
      label.position.set(0,2.4,-zone.depth*.3);label.scale.set(Math.min(3,zone.width),Math.min(3,zone.width)/4,1);kitchen.add(label)
      this.register(kitchen, { title: zone.name, type: '厨房房间', detail: '房门、人员路径与分区烟气使用同一空间节点。',
        fireRoom: { floor: zone.floor, room: zone.id.endsWith(':east') ? 'east' : 'west' }, x: zone.x, y: zone.y })
    }
    for (const door of this.initial.doors.filter(door => door.floor === floor)) {
      const room = this.initial.zones.find(zone => zone.id === door.room_id)
      const passage = this.passages.find(edge => (edge as Passage & { id?: string }).id === door.id)
      const hall = passage?.end ?? this.initial.zones.find(zone => zone.kind === 'corridor' && zone.floor === floor)
      if (!room || !hall) continue
      const opening = this.doorPosition(room, hall), width = this.passages.find(edge => (edge as Passage & { id?: string }).id === door.id)?.width_meters ?? .9
      const frame = new THREE.Group(); frame.position.copy(this.point(opening.x, opening.y, room.height))
      frame.rotation.y = Math.atan2(hall.x - room.x, hall.y - room.y); layer.add(frame)
      for (const side of [-1, 1]) box(frame, .06, 2.14, .1, 0x8b7257, side * (width / 2 + .03), 1.07, 0)
      box(frame, width + .12, .08, .1, 0x8b7257, 0, 2.18, 0)
      const hinge = new THREE.Group(); hinge.position.x = -width / 2; frame.add(hinge)
      box(hinge, width, 2.1, .045, 0xb89467, width / 2, 1.05, 0)
      box(hinge, .035, .12, .08, 0x344e46, width - .12, 1, .05)
      this.doors.set(door.id, hinge)
    }
  }

  private doorPosition(room: IndoorZone, hall: {x: number; y: number}) {
    const dx = hall.x - room.x, dy = hall.y - room.y
    const t = Math.min(1, Math.abs(dx) > .001 ? room.width / (2 * Math.abs(dx)) : Infinity,
      Math.abs(dy) > .001 ? room.depth / (2 * Math.abs(dy)) : Infinity)
    return { x: room.x + dx * t, y: room.y + dy * t }
  }

  update(state: IndoorState, floor?: number) {
    const selected = floor ?? state.zones.find(zone => zone.id === state.source_zone_id)?.floor ?? 1
    if (!this.floors.has(selected)) this.buildFloor(selected)
    for (const [level, group] of this.floors) group.visible = level === selected
    for (const zone of state.zones) {
      const mesh = this.volumes.get(zone.id)
      if (mesh) { mesh.visible = zone.smoke_density > .005; mesh.material.opacity = Math.min(.45, zone.smoke_density * .55); mesh.material.color.setHex(zone.smoke_density > .55 ? 0x6f5145 : 0xb39b70) }
    }
    for (const door of state.doors) {
      const hinge = this.doors.get(door.id)
      if (hinge) hinge.rotation.y = door.state === 'open' ? -Math.PI / 2 : 0
    }
  }
}
