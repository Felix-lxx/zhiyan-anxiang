import * as THREE from 'three'
import type { Vehicle } from '../domain/drill'
import { fitVehicleModel, poseVehicleWheels, poseAmbulanceRearDoors, type VehicleWheel } from './vehicleModel'
import { VEHICLE_GROUND_Y } from './roadSurface'
import { ActorMotion } from './actorMotion'
import { routeHeading } from './routeHeading'

function dispose(root: THREE.Object3D) {
  root.traverse(object => {
    const mesh = object as THREE.Mesh
    mesh.geometry?.dispose()
    if (mesh.material) for (const material of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
      for (const value of Object.values(material)) if (value instanceof THREE.Texture) value.dispose()
      material.dispose()
    }
  })
  root.removeFromParent()
}

/** Presents confirmed vehicle positions. Loading and animation never advance the simulation. */
export class VehicleVisuals {
  readonly layer = new THREE.Group()
  private models = new Map<string, THREE.Group>()
  private motion = new ActorMotion()
  private requests = new Set<AbortController>()
  private disposed = false
  constructor(private register: (object: THREE.Object3D) => void, private dirty: () => void) {}

  update(vehicles: Vehicle[], elapsed: number, running: boolean) {
    const present = new Set(vehicles.map(vehicle => vehicle.id))
    for (const [id, root] of this.models) root.visible = present.has(id)
    for (const vehicle of vehicles) {
      let root = this.models.get(vehicle.id)
      const initial = !root
      if (!root) {
        root = this.create(vehicle); this.models.set(vehicle.id, root); this.layer.add(root)
        void this.load(root, vehicle)
      }
      root.visible = true;root.userData.vehicle=vehicle
      const modelNotice=root.userData.assetStatus==='fallback'?'车辆使用轻量模型。':''
      const detail = modelNotice+(vehicle.service ? `${vehicle.service.label} · 剩余 ${vehicle.service.remaining_seconds} 秒。${vehicle.service.reason}` : `${vehicle.reason}${vehicle.passenger ? ` 车内人员：${vehicle.passenger.label}。` : ''}${vehicle.remaining_seconds === null ? '' : ` 剩余 ${vehicle.remaining_seconds} 秒。`}`)
      root.traverse(object => { object.userData.selection = { title: vehicle.name, type: '可调度应急车辆', detail, vehicleId: vehicle.id, x: vehicle.x, y: vehicle.y } })
      root.userData.moving = vehicle.state === 'moving'
      root.userData.beacon.visible = running && (vehicle.state === 'moving' || Boolean(vehicle.service))
      const position = new THREE.Vector3(vehicle.x - 50, VEHICLE_GROUND_Y, vehicle.y - 50)
      const route = vehicle.route_points.map(point => new THREE.Vector3(point.x - 50, VEHICLE_GROUND_Y, point.y - 50))
      this.motion.accept(root, position, route, elapsed, running)
      const heading = Number.isFinite(vehicle.heading_radians) ? vehicle.heading_radians : routeHeading(position, route)
      if ((initial || !running) && heading !== undefined) {
        root.rotation.y = heading
        root.userData.heading = root.rotation.y
        poseVehicleWheels(root.userData.wheels ?? [], 0, 0)
      }
      if (!running && vehicle.kind === 'ambulance') {
        const doorTarget = vehicle.service?.action === 'load' && vehicle.service.remaining_seconds <= 12 ? 1 : 0
        root.userData.rearDoorOpen = doorTarget
        poseAmbulanceRearDoors(root.userData.body, doorTarget)
      }
    }
    this.dirty()
  }

  get failedCount(){return [...this.models.values()].filter(root=>root.visible&&root.userData.assetStatus==='fallback').length}
  get loadingCount(){return [...this.models.values()].filter(root=>root.visible&&root.userData.assetStatus==='loading').length}
  async retryFailed(){
    if(this.disposed)return
    await Promise.allSettled([...this.models.values()].filter(root=>root.visible&&root.userData.assetStatus==='fallback').map(root=>this.load(root,root.userData.vehicle)))
  }

  step(delta: number, running: boolean, time: number, effects: boolean) {
    for (const root of this.models.values()) {
      if (!root.visible) continue
      const distance=this.motion.step(root,delta,running)
      const turn=Math.atan2(Math.sin(root.rotation.y-(root.userData.heading??root.rotation.y)),Math.cos(root.rotation.y-(root.userData.heading??root.rotation.y)))
      root.userData.heading=root.rotation.y
      if(running){
        const target=distance>.0001?THREE.MathUtils.clamp(Math.atan(2.8*turn/distance),-.45,.45):0
        root.userData.steering=THREE.MathUtils.damp(root.userData.steering??0,target,12,delta)
        poseVehicleWheels(root.userData.wheels??[],distance,root.userData.steering)
      }
      if (root.userData.vehicle?.kind === 'ambulance') {
        const service = (root.userData.vehicle as Vehicle).service
        const target = service?.action === 'load' && service.remaining_seconds <= 12 ? 1 : 0
        const openness = running ? THREE.MathUtils.damp(root.userData.rearDoorOpen ?? 0, target, 5, delta) : target
        root.userData.rearDoorOpen = openness
        poseAmbulanceRearDoors(root.userData.body, openness)
      }
      const beacon = root.userData.beacon as THREE.Mesh
      if (beacon.visible) (beacon.material as THREE.MeshBasicMaterial).opacity = effects ? .55 + Math.sin(time * 8) ** 2 * .45 : .8
    }
  }

  private create(vehicle: Vehicle) {
    const root = new THREE.Group(), body = new THREE.Group()
    root.name = vehicle.id
    const box = (w: number, h: number, d: number, color: number, x: number, y: number, z: number) => {
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), new THREE.MeshStandardMaterial({ color, roughness: .65 }))
      mesh.position.set(x, y, z); mesh.castShadow = true; body.add(mesh)
    }
    const firetruck = vehicle.kind === 'firetruck', length = firetruck ? 6.2 : 5.2
    box(2.1, 1.5, length, firetruck ? 0xb74131 : 0xe8ece3, 0, 1.3, 0)
    box(1.9, .7, 1.3, 0x294d58, 0, 2, -length / 2 + .8)
    box(2.13, .2, length - .2, 0xe9dfb8, 0, 1.25, 0)
    const wheels:VehicleWheel[]=[]
    for (const side of [-1, 1]) for (const axle of [-1, 1]) {
      const wheel = new THREE.Mesh(new THREE.CylinderGeometry(.43, .43, .26, 12), new THREE.MeshStandardMaterial({ color: 0x262c30 }))
      wheel.rotation.z = Math.PI / 2; wheel.position.set(side * (firetruck?1.09:1.01), .43, axle * length * .3); body.add(wheel)
      wheels.push({object:wheel,radius:.43,rest:wheel.quaternion.clone(),front:axle<0,rollSign:-1})
    }
    const beacon = new THREE.Mesh(new THREE.BoxGeometry(1.4, .16, .32), new THREE.MeshBasicMaterial({ color: 0x60c8ff, transparent: true }))
    beacon.position.set(0, 2.5, -length / 2 + 1)
    root.add(body, beacon); root.userData.body = body; root.userData.beacon = beacon;root.userData.wheels=wheels;root.userData.assetStatus='loading'
    this.register(root)
    return root
  }

  private async load(root: THREE.Group, vehicle: Vehicle) {
    const controller = new AbortController(); this.requests.add(controller)
    const timeout = setTimeout(() => controller.abort(), 15000)
    let candidate:THREE.Group|undefined
    let textureUrl:string|undefined
    root.userData.assetStatus='loading';this.dirty()
    try {
      const url = `${import.meta.env.BASE_URL}assets/kenney-car-kit/${vehicle.kind}.glb`
      const [{ GLTFLoader }, response, texture]=await Promise.all([
        import('three/examples/jsm/loaders/GLTFLoader.js'),
        fetch(url,{signal:controller.signal}),
        fetch(`${import.meta.env.BASE_URL}assets/kenney-car-kit/Textures/colormap.png`,{signal:controller.signal}),
      ])
      if(!response.ok||!texture.ok)throw new Error('车辆模型或纹理读取失败')
      const [buffer,image]=await Promise.all([response.arrayBuffer(),texture.blob()])
      textureUrl=URL.createObjectURL(image)
      const manager=new THREE.LoadingManager()
      // ImageBitmapLoader fetches blob: URLs through connect-src. Use the
      // image loader for our already fetched local atlas; img-src permits it
      // without weakening the application's network security policy.
      manager.addHandler(/(?:^|\/)Textures\/colormap\.png$/,new THREE.TextureLoader(manager))
      manager.setURLModifier(resource=>{
        if(resource.endsWith('/Textures/colormap.png'))return textureUrl!
        if(resource.startsWith('data:')||resource.startsWith('blob:'))return resource
        throw new Error('车辆资源引用了未打包的外部文件')
      })
      const {scene}=await new GLTFLoader(manager).parseAsync(buffer,url.slice(0,url.lastIndexOf('/')+1));candidate=scene
      if (this.disposed) { dispose(scene); return }
      scene.traverse(object=>{
        if(!(object as THREE.Mesh).isMesh)return
        const material=(object as THREE.Mesh).material
        for(const item of Array.isArray(material)?material:[material]){
          const map=(item as THREE.MeshStandardMaterial).map
          const decoded: unknown = map?.image
          if(typeof decoded!=='object'||decoded===null||!('width' in decoded)||typeof decoded.width!=='number'||decoded.width<=0) {
            throw new Error('车辆颜色纹理未能加载')
          }
        }
      })
      const wheels=fitVehicleModel(scene,vehicle.kind==='firetruck'?6.2:5.2,Math.min(vehicle.kind==='firetruck'?2.45:2.3,vehicle.minimum_width-.2))
      scene.traverse(object => {
        object.userData.selection = root.userData.selection
        if ((object as THREE.Mesh).isMesh) { object.castShadow = true; object.receiveShadow = true }
      })
      const modelHeight=new THREE.Box3().setFromObject(scene).max.y
      dispose(root.userData.body); root.add(scene); root.userData.body = scene;candidate=undefined
      root.userData.wheels=wheels;root.userData.assetStatus='ready'
      root.userData.beacon.position.y=modelHeight+.08
      this.dirty()
    } catch { if(candidate)dispose(candidate);if(!this.disposed){root.userData.assetStatus='fallback';this.dirty()} }
    finally { clearTimeout(timeout);controller.abort();if(textureUrl)URL.revokeObjectURL(textureUrl);this.requests.delete(controller) }
  }

  dispose() {
    this.disposed = true
    for (const request of this.requests) request.abort()
    this.motion.clear(); dispose(this.layer); this.models.clear()
  }
}
