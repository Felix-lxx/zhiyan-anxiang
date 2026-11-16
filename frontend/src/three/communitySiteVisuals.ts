import * as THREE from 'three'
import { planCommunitySite, type SiteFeature, type SiteInput } from './communitySite'
import { createStreetFurniture } from './communityModels'
import { fitSiteAsset } from './siteAssetFit'
import type { SceneMaterials } from './sceneMaterials'
import { batchStaticParts } from './staticMeshBatch'

/** Presentation-only context. Every solid occupies a pre-checked ground reservation. */
export class CommunitySiteVisuals {
  readonly group=new THREE.Group()
  readonly plan:SiteFeature[]
  private details=new THREE.Group()
  private roots=new Map<string,THREE.Group>()
  private sources:THREE.Object3D[]=[]
  private controllers=new Set<AbortController>()
  private closed=false

  constructor(input:SiteInput,materials:SceneMaterials,private changed:()=>void) {
    this.group.name='community-site-context'
    this.plan=planCommunitySite(input)
    this.group.userData.sitePlan=this.plan
    this.group.add(this.details)
    const curb=materials.surface('stone',0xa5a398,2,1)
    for(const feature of this.plan) {
      const root=new THREE.Group();root.name=feature.id
      root.position.set(feature.x-50,0,feature.y-50)
      root.userData.siteFootprint={...feature};this.group.add(root);this.roots.set(feature.id,root)
      if(feature.kind==='garden') {
        const lawn=new THREE.Mesh(new THREE.PlaneGeometry(feature.width-.18,feature.depth-.18),materials.surface('grass',0xe4ead7,2,1.5))
        lawn.rotation.x=-Math.PI/2;lawn.position.y=.026;lawn.receiveShadow=true;root.add(lawn)
        for(const side of [-1,1]) {
          this.solid(root,feature.width,.12,.1,0,.06,side*(feature.depth/2-.05),curb)
          this.solid(root,.1,.12,feature.depth-.2,side*(feature.width/2-.05),.06,0,curb)
        }
        batchStaticParts(root)
      } else if(feature.kind==='bench') {
        const fallback=fitSiteAsset(createStreetFurniture(),3.4,1.25,1.25,true)
        fallback.name='bench-fallback';root.add(fallback)
      } else {
        const paint=new THREE.MeshStandardMaterial({color:0xd6d1b8,roughness:.9})
        for(const side of [-1,1])this.solid(root,.06,.004,feature.depth,side*(feature.width/2-.1),.013,0,paint)
        this.solid(root,feature.width-.2,.004,.06,0,.013,feature.depth/2-.1,paint)
      }
    }
  }

  private solid(root:THREE.Group,w:number,h:number,d:number,x:number,y:number,z:number,material:THREE.Material) {
    const mesh=new THREE.Mesh(new THREE.BoxGeometry(w,h,d),material)
    mesh.position.set(x,y,z);mesh.castShadow=true;mesh.receiveShadow=true;root.add(mesh)
  }

  private async source(relative:string) {
    const {GLTFLoader}=await import('three/examples/jsm/loaders/GLTFLoader.js')
    if(this.closed)throw new Error('Scene closed')
    const url=`${import.meta.env.BASE_URL}assets/${relative}`
    const controller=new AbortController();this.controllers.add(controller)
    const timeout=window.setTimeout(()=>controller.abort(),15000)
    try {
      const response=await fetch(url,{signal:controller.signal})
      if(!response.ok)throw new Error(`Model HTTP ${response.status}`)
      const loaded=await new GLTFLoader().parseAsync(await response.arrayBuffer(),url.slice(0,url.lastIndexOf('/')+1))
      this.sources.push(loaded.scene)
      if(this.closed){this.release([loaded.scene]);throw new Error('Scene closed')}
      return loaded.scene
    } finally {window.clearTimeout(timeout);this.controllers.delete(controller)}
  }

  async load() {
    const jobs=[
      {kind:'bench',url:'community-real/painted_wooden_bench/painted_wooden_bench.gltf'},
      {kind:'garden',url:'kenney-city-suburban/Models/GLB%20format/tree-large.glb'},
      {kind:'parking',url:'kenney-car-kit/sedan.glb'},
      {kind:'shrub',url:'community-real/shrub_02/shrub_02.gltf'},
    ] as const
    const results=await Promise.allSettled(jobs.map(async job=>{
      if(!this.plan.some(f=>f.kind===(job.kind==='shrub'?'garden':job.kind)))return false
      const source=await this.source(job.url)
      for(const [index,feature] of this.plan.filter(f=>f.kind===(job.kind==='shrub'?'garden':job.kind)).entries()) {
        if(this.closed)return
        const root=this.roots.get(feature.id)!
        if(job.kind==='bench') {
          const model=fitSiteAsset(source,2.1,1.1,1.1,true)
          model.name='scanned-community-bench';root.add(model)
          const fallback=root.getObjectByName('bench-fallback')
          if(fallback){root.remove(fallback);this.release([fallback])}
        } else if(job.kind==='parking') {
          const model=fitSiteAsset(source,2.35,5.1,1.75,true)
          model.name='parked-community-car';root.add(model)
        } else if(job.kind==='garden') {
          if(index%2 || index>=12)continue
          const model=fitSiteAsset(source,3.3,3.3,5.6)
          model.position.y=.035;model.name='community-tree';root.add(model)
        } else {
          if(index>=6)continue
          for(const side of [-1,1]) {
            const model=fitSiteAsset(source,2.1,1.7,1.05)
            model.position.set(feature.x-50+side*Math.min(2.5,feature.width/2-1.25),.035,feature.y-50+.7)
            model.name='scanned-community-shrub';model.userData.siteFeature=feature.id;this.details.add(model)
          }
        }
      }
      this.group.traverse(object=>{if(object instanceof THREE.Mesh){object.castShadow=true;object.receiveShadow=true}})
      this.changed()
      return true
    }))
    return {loaded:results.filter(r=>r.status==='fulfilled'&&r.value===true).length,
      failed:results.filter(r=>r.status==='rejected').length}
  }

  setQuality(quality:'low'|'medium'|'high') {this.details.visible=quality==='high'}

  private release(roots:THREE.Object3D[]) {
    const geometries=new Set<THREE.BufferGeometry>(),materials=new Set<THREE.Material>(),textures=new Set<THREE.Texture>()
    for(const root of roots)root.traverse(object=>{
      if(!(object instanceof THREE.Mesh))return
      geometries.add(object.geometry)
      for(const material of Array.isArray(object.material)?object.material:[object.material]) {
        materials.add(material)
        for(const value of Object.values(material))if(value instanceof THREE.Texture)textures.add(value)
      }
    })
    geometries.forEach(g=>g.dispose());materials.forEach(m=>m.dispose());textures.forEach(t=>t.dispose())
  }

  dispose() {
    this.closed=true;this.controllers.forEach(c=>c.abort());this.controllers.clear()
    this.release([this.group,...this.sources]);this.group.clear();this.sources=[];this.roots.clear()
  }
}
