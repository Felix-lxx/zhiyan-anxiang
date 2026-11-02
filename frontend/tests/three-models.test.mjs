import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import ts from 'typescript'
import * as THREE from 'three'

// Compile pure rendering factories without a browser or generated source files.
const require = createRequire(import.meta.url)
const threeUrl = pathToFileURL(require.resolve('three').replace(/three\.cjs$/, 'three.module.js')).href
const moduleUrls=new Map()
async function moduleUrl(name){
  if(moduleUrls.has(name))return moduleUrls.get(name)
  const pending=(async()=>{
    const source=await readFile(new URL('../src/three/'+name+'.ts',import.meta.url),'utf8')
    let code=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText
    code=code.replace(/from ['"]three['"]/g,`from '${threeUrl}'`).replace(/from ['"](three\/examples\/[^'"]+)['"]/g,(_,path)=>`from '${pathToFileURL(require.resolve(path)).href}'`)
    for(const match of [...code.matchAll(/from ['"]\.\/([^'"]+)['"]/g)])code=code.replace(match[0],`from '${await moduleUrl(match[1])}'`)
    return 'data:text/javascript;base64,'+Buffer.from(code).toString('base64')
  })()
  moduleUrls.set(name,pending);return pending
}
async function load(name){return import(await moduleUrl(name))}
const { displayHeight } = await load('sceneMaterials')
const { createPerson, posePerson, createPatrolRobot } = await load('actors')
const { RoadVisuals } = await load('roadVisuals')
const { CrowdRenderer } = await load('crowdRenderer')
const { presentHelpers, meetingRoute } = await load('helperPresentation')
const { createRouteGuide } = await load('routeGuide')
const { cutFloor, stairOpenings, furnitureFits, floorContainsHeight, doorPortal, doorWallPanels, fireSourceCamera, kitchenCamera } = await load('indoorGeometry')

test('fire selection camera keeps every candidate footprint inside wide and narrow viewports', () => {
  const objects = [{x:-20,y:-15,width:10,depth:6},{x:20,y:15,width:10,depth:6}]
  for (const aspect of [2.1,1,.45]) {
    const camera = new THREE.PerspectiveCamera(48,aspect,.1,400)
    const frame = fireSourceCamera(objects,aspect)
    camera.position.copy(frame.position); camera.lookAt(frame.target); camera.updateMatrixWorld()
    for (const object of objects) for (const dx of [-5,5]) for (const dz of [-3,3]) {
      const projected = new THREE.Vector3(object.x+dx,4,object.y+dz).project(camera)
      assert.ok(Math.abs(projected.x)<1 && Math.abs(projected.y)<1,'Candidate must be visible and clickable')
    }
  }
})

test('kitchen front partitions leave the frozen door and body clearance open', () => {
  const room = {x:10,y:10,width:4,depth:4}
  const opening = doorPortal(room,{x:10,y:13},.9)
  const panels = doorWallPanels(room,opening)
  assert.equal(panels.length,2)
  const passage = {kind:'room',width_meters:.9,start:{x:10,y:10,height:0},end:{x:10,y:13,height:0}}
  for(const panel of panels) {
    assert.ok(furnitureFits(panel,0,[passage]))
    assert.ok(panel.x-panel.width/2>=8-1e-8 && panel.x+panel.width/2<=12+1e-8)
  }
})

test('door portal follows passage orientation and open leaf clears the walking envelope', () => {
  const room={x:10,y:10,width:4,depth:4}
  for(const hall of [{x:10,y:16},{x:16,y:10},{x:10,y:4},{x:4,y:10}]) {
    const portal=doorPortal(room,hall,1.2)
    assert.equal(Math.hypot(portal.x-room.x,portal.y-room.y),2)
    const direction=new THREE.Vector3(0,0,1).applyAxisAngle(new THREE.Vector3(0,1,0),portal.rotation)
    assert.ok(direction.dot(new THREE.Vector3(hall.x-room.x,0,hall.y-room.y).normalize())>.9999)
    const leaf=new THREE.Mesh(new THREE.BoxGeometry(portal.width,2.1,.045))
    leaf.position.set(portal.width/2,1.05,0)
    const hinge=new THREE.Group();hinge.add(leaf);hinge.position.x=portal.hingeX;hinge.rotation.y=portal.openAngle
    const handle=new THREE.Mesh(new THREE.BoxGeometry(.035,.12,.08))
    handle.position.set(portal.width-.12,1,-.05);hinge.add(handle)
    const bounds=new THREE.Box3().setFromObject(hinge)
    assert.ok(bounds.max.x < -portal.width/2,'Open leaf must stay outside navigable width')
    assert.ok(bounds.max.z < .03,'Open leaf must not extend into the corridor')
    leaf.geometry.dispose();leaf.material.dispose();handle.geometry.dispose();handle.material.dispose()
  }
})

test('indoor floors leave a stair opening and reject furnishings intersecting walking space', () => {
  const stair={kind:'stairs',width_meters:1.2,start:{x:2,y:2,height:.18},end:{x:2,y:6,height:3.38}}
  const rect={x:5,y:5,width:10,depth:10}, holes=stairOpenings([stair],3.38)
  const slabs=cutFloor(rect,holes)
  assert.ok(slabs.length>1)
  const hole=holes[0]
  for(const slab of slabs)assert.ok(Math.abs(slab.x-hole.x)>=(slab.width+hole.width)/2-.0001||Math.abs(slab.y-hole.y)>=(slab.depth+hole.depth)/2-.0001)
  assert.ok(slabs.reduce((sum,slab)=>sum+slab.width*slab.depth,0)<100)
  assert.equal(furnitureFits({x:2,y:4,width:1,depth:1},.18,[stair]),false)
  assert.equal(furnitureFits({x:8,y:8,width:1,depth:1},.18,[stair]),true)
  for(let height=.3;height<=3.38;height+=.2)assert.equal(floorContainsHeight(height,3.38,.24),true)
  assert.equal(floorContainsHeight(6.58,3.38,.24),false)
})

test('route arrows retain confirmed corners and stair height with a bounded mesh count', () => {
  const points=[new THREE.Vector3(0,0,0),new THREE.Vector3(0,0,10),new THREE.Vector3(10,3,10)]
  const guide=createRouteGuide(points,0x85ddff)
  assert.equal(guide.children.length,2)
  const line=guide.children[0].geometry.getAttribute('position')
  points.forEach((p,i)=>assert.ok(new THREE.Vector3().fromBufferAttribute(line,i).distanceTo(p)<.00001))
  const arrows=guide.getObjectByName('route-direction-marks').geometry.getAttribute('position')
  assert.ok(arrows.count<=24)
  for(let i=0;i<arrows.count;i+=4) {
    const tip=new THREE.Vector3().fromBufferAttribute(arrows,i)
    assert.ok(Math.abs(tip.x)<.00001 ? tip.z>=0&&tip.z<=10 : Math.abs(tip.z-10)<.00001&&Math.abs(tip.y-tip.x*.3)<.00001)
  }
  assert.equal(createRouteGuide([points[0],points[0]],0xffffff).children.length,0)
})

test('staff reuse keeps one physical actor and meeting paths preserve corridor corners', () => {
  const route = [{x:0,y:0,height:0},{x:0,y:10,height:0},{x:10,y:10,height:3}]
  const old = {id:'old',staff_id:'staff-1',state:'completed',x:0,y:0}
  const active = {id:'new',staff_id:'staff-1',state:'approaching',x:0,y:0,route_points:route}
  assert.deepEqual(presentHelpers([old,active]),[active])
  assert.deepEqual(presentHelpers([active,old]),[active])
  assert.deepEqual(meetingRoute(active),route)
  assert.deepEqual(meetingRoute({...active,route_reachable:false}),[])
  assert.deepEqual(meetingRoute({...active,route_points:[]}),[])
})

test('1000 residents share five instance batches; detail pool stays bounded and selection survives reuse', () => {
  const actors = Array.from({length:1000}, (_, i) => {
    const actor = new THREE.Group(); actor.name = `resident-${i}`
    actor.position.set(i % 32, 0, Math.floor(i / 32)); actor.userData.selection = { residentId: actor.name }
    return actor
  })
  let created = 0
  const crowd = new CrowdRenderer(actors, () => { created++; return new THREE.Group() })
  const camera = new THREE.PerspectiveCamera(); camera.position.set(0, 5, 5)
  crowd.update(camera, new Set(), 12, 1, true, () => {})
  assert.equal(created, 12)
  assert.equal(crowd.group.children.filter(o=>o.isInstancedMesh).length, 5)
  assert.equal(crowd.selection(999).residentId, 'resident-999')
  for(let t=2;t<30;t++) {
    camera.position.x = t
    crowd.update(camera, new Set(['resident-999']), 12, t, true, () => {})
  }
  assert.equal(created, 12)
  assert.equal(actors[999].children.length, 1)
  assert.equal(actors[999].children[0].userData.selection.residentId, 'resident-999')
  crowd.update(camera, new Set(), 6, 31, true, () => {})
  assert.equal(actors.filter(a=>a.children.length).length, 6)
  assert.equal(crowd.group.children.filter(o=>!o.isInstancedMesh).length, 6, 'unused slots remain owned for disposal')
})

test('road risk updates reuse meshes, refresh selection and rebuild only on topology changes', () => {
  const visuals = new RoadVisuals()
  const road = { id: 'north', name: '北门通道', start: { x: 50, y: 20 }, end: { x: 50, y: 40 }, width_meters: 4, status: 'open', risk_score: 0 }
  assert.equal(visuals.update([road], edge => edge.status), true)
  const mesh = visuals.meshes.get(road.id), geometry = mesh.geometry, heat = visuals.heat
  for (let risk = 1; risk <= 100; risk++) {
    assert.equal(visuals.update([{ ...road, risk_score: risk, density_percent: risk }], edge => edge.status), false)
    assert.equal(visuals.meshes.get(road.id).geometry, geometry)
    assert.equal(visuals.heat, heat)
  }
  visuals.update([{ ...road, status: 'blocked' }], edge => edge.status)
  assert.equal(mesh.userData.selection.detail, 'blocked')
  assert.equal(mesh.userData.selection.action, undefined)
  assert.equal(mesh.material.opacity, .72)
  assert.equal(visuals.update([{ ...road, width_meters: 2 }], edge => edge.status), true)
  assert.notEqual(visuals.meshes.get(road.id).geometry, geometry)
  visuals.dispose()
  assert.equal(visuals.group.children.length, 0)
})
const { createApartment } = await load('communityModels')
const { FireEffects } = await load('fireEffects')
const { ActorMotion } = await load('actorMotion')

test('actual lane trace bridges snapshots without snapping or cutting the turn', () => {
  const motion = new ActorMotion(), actor = new THREE.Group()
  const p=(x,z)=>new THREE.Vector3(x,0,z)
  motion.accept(actor,p(0,0),[p(0,0),p(4,0),p(4,4)],0,true,0)
  const trace=[p(0,0),p(2,.25),p(4,0),p(4.25,2)]
  motion.accept(actor,trace[3],[trace[3],p(4,4)],1,true,1000,trace)
  assert.ok(actor.position.equals(trace[0]),'A lateral offset must not force an immediate snap')
  motion.step(actor,1/3,true)
  assert.ok(actor.position.distanceTo(trace[1])<1e-8,'Follow the confirmed curved lane before the corner')
  motion.step(actor,10,true)
  assert.ok(actor.position.distanceTo(trace[3])<1e-8,'Stop exactly at confirmed position')
})

test('a newly closed door never animates delayed actors through its leaf', () => {
  const motion=new ActorMotion(),actor=new THREE.Group()
  const a=new THREE.Vector3(0,0,0),b=new THREE.Vector3(0,0,2)
  motion.accept(actor,a,[a,b],0,true,0)
  const barrier={position:new THREE.Vector3(0,0,1),normal:new THREE.Vector3(0,0,1),width:.9,radius:.28}
  motion.accept(actor,b,[b],1,true,1000,[a,b],[barrier])
  assert.ok(actor.position.equals(b),'Reconcile to authority when visual history crosses a now-closed door')
  assert.equal(motion.step(actor,.5,true),0)
  motion.clear()
  motion.accept(actor,a,[a,b],0,true,0)
  motion.accept(actor,b,[b],1,true,1000,[a,b])
  assert.ok(actor.position.equals(a))
  motion.accept(actor,b,[b],1,true,1100,[a,b],[barrier])
  assert.ok(actor.position.equals(b),'A door-only update must cancel an already queued crossing')
})
const { assemblyAttendance } = await load('assemblyPoint')

test('assembly marker only counts confirmed arrivals at its own node', () => {
  const people = [
    {id:'1',status:'evacuated',node_id:'assembly:north',counted:true,exit:'north'},
    {id:'2',status:'evacuated',node_id:'assembly:north',counted:false,exit:'north'},
    {id:'3',status:'moving',node_id:'road:north',counted:false,exit:'north'},
    {id:'4',status:'evacuated',node_id:'assembly:south',counted:true,exit:'south'},
    {id:'5',status:'missing',node_id:'home:room',counted:false,exit:'north'},
  ]
  assert.deepEqual(assemblyAttendance(people,'assembly:north'),{arrived:2,counted:1,pending:1,inbound:2})
  assert.deepEqual(assemblyAttendance(people,'assembly:south'),{arrived:1,counted:1,pending:0,inbound:0})
  assert.equal(assemblyAttendance(people.map(p=>({...p,status:'waiting',counted:false})),'assembly:north').arrived,0,'historical rewind must clear arrival counts')
})

test('confirmed movement follows route corners, stops at snapshot and snaps on rewind', () => {
  const motion = new ActorMotion(), actor = new THREE.Group()
  const p = (x, z) => new THREE.Vector3(x, 0, z)
  motion.accept(actor, p(0, 0), [p(0, 0), p(1, 0), p(1, 2)], 0, true, 0)
  motion.accept(actor, p(1, 1), [p(1, 1), p(1, 2)], 1, true, 1000)
  motion.step(actor, .25, true)
  assert.ok(actor.position.distanceTo(p(.5, 0)) < 1e-8, 'must follow first corridor, not cut diagonally')
  motion.step(actor, .5, true)
  assert.ok(actor.position.distanceTo(p(1, .5)) < 1e-8)
  motion.step(actor, 5, true)
  assert.ok(actor.position.distanceTo(p(1, 1)) < 1e-8, 'must never predict beyond confirmed position')
  motion.accept(actor, p(0, 0), [], 0, true, 1300)
  assert.equal(actor.position.length(), 0, 'history seek is not a reverse walk')
})

test('full robot routes are trimmed, selection does not restart motion, pause reconciles', () => {
  const motion = new ActorMotion(), actor = new THREE.Group()
  const p = x => new THREE.Vector3(x, 0, 0), route = [p(0), p(10), p(20)]
  motion.accept(actor, p(12), route, 10, true, 0)
  motion.accept(actor, p(14), route, 11, true, 1000)
  motion.step(actor, .25, true)
  assert.equal(actor.position.x, 12.5)
  motion.accept(actor, p(14), route, 11, true, 1100)
  motion.step(actor, .25, true)
  assert.equal(actor.position.x, 13)
  motion.step(actor, .01, false)
  assert.equal(actor.position.x, 14)
  motion.clear()
})

test('replanned or disconnected positions reconcile without an invented diagonal', () => {
  const motion = new ActorMotion(), actor = new THREE.Group()
  motion.accept(actor, new THREE.Vector3(), [new THREE.Vector3(), new THREE.Vector3(10, 0, 0)], 1, true, 0)
  const changed = new THREE.Vector3(0, 0, 2)
  motion.accept(actor, changed, [changed, new THREE.Vector3(0, 0, 10)], 2, true, 1000)
  assert.ok(actor.position.equals(changed))
  assert.equal(motion.step(actor, 1, true), 0)
})

test('missing routes cannot invent movement and continuous reversal preserves corners', () => {
  const motion = new ActorMotion(), actor = new THREE.Group()
  const p = (x, z) => new THREE.Vector3(x, 0, z)
  motion.accept(actor, p(0, 0), [], 0, true, 0)
  motion.accept(actor, p(4, 4), [], 1, true, 1000)
  assert.ok(actor.position.equals(p(4, 4)), 'no geometry means reconcile, not diagonal animation')
  assert.equal(motion.step(actor, .2, true), 0)
  motion.clear()
  motion.accept(actor, p(1, 1), [p(1, 1), p(1, 2)], 0, true, 0)
  motion.accept(actor, p(.5, 0), [p(1, 1), p(1, 0), p(0, 0)], 1, true, 1000)
  motion.step(actor, .5, true)
  assert.ok(actor.position.distanceTo(p(1, .25)) < 1e-8, 'retreat follows actual corner')
})

test('both apartment detail levels have a real unobstructed front doorway', () => {
  const building = createApartment(12, 8, 5, 4, true)
  building.updateMatrixWorld(true)
  const ray = new THREE.Raycaster(new THREE.Vector3(0, 1.4, 6), new THREE.Vector3(0, 0, -1), 0, 4)
  for (const level of building.levels) {
    assert.equal(ray.intersectObject(level.object, true).length, 0, 'doorway must not be backed by a solid shell or door leaf')
    const wall = new THREE.Raycaster(new THREE.Vector3(4, 1.4, 6), new THREE.Vector3(0, 0, -1), 0, 4)
    assert.ok(wall.intersectObject(level.object, true).length > 0)
  }
})

test('legacy snapshots align rooms, floors and full-height facades without changing simulation coordinates', () => {
  assert.equal(displayHeight(0), 0)
  for(let floor=1;floor<=12;floor++) {
    const foot=displayHeight(floor*1.92)
    assert.ok(Math.abs(foot-((floor-1)*3.2+.18))<1e-9)
    assert.ok(foot+1.92<floor*3.2, 'resident fits below its floor ceiling')
  }
  for(let h=0;h<=24;h+=.1)assert.ok(displayHeight(h+.1)>=displayHeight(h),'continuous monotonic stair elevation')
  const building=createApartment(12,9,7,12,true)
  assert.equal(building.scale.y,1)
  assert.equal(building.levels.length,2)
  assert.ok(new THREE.Box3().setFromObject(building).max.y>=7*3.2)
})

test('resident motion stops cleanly and risk changes never alter its physical scale', () => {
  const person=createPerson('resident-08',true)
  const scale=person.scale.clone()
  posePerson(person,true,1,false,false)
  assert.ok(person.userData.limbs.some(l=>Math.abs(l.rotation.x)>0))
  posePerson(person,false,2,false,false)
  assert.ok(person.userData.limbs.every(l=>l.rotation.x===0))
  posePerson(person,false,2,true,true)
  assert.equal(person.userData.torso.rotation.x,-.22)
  assert.deepEqual(person.scale,scale)
  assert.equal(createPatrolRobot().userData.wheels.length,4)
})

test('fire and smoke are deterministic, bounded, quality-scaled and extinguish at zero intensity', () => {
  const effects=new FireEffects(), camera=new THREE.PerspectiveCamera()
  effects.update(18,40,12,'东风',camera,1)
  assert.equal(effects.group.children.length,2)
  const before=effects.group.children.map(mesh=>Array.from(mesh.instanceMatrix.array))
  effects.update(18,40,12,'东风',camera,1)
  effects.group.children.forEach((mesh,i)=>assert.deepEqual(Array.from(mesh.instanceMatrix.array),before[i]))
  effects.update(18,40,12,'东风',camera,.45)
  assert.deepEqual(effects.group.children.map(mesh=>mesh.count),[29,40])
  effects.group.children.forEach(mesh=>assert.ok(Array.from(mesh.instanceMatrix.array).every(Number.isFinite)))
  effects.update(18,0,12,'东风',camera,1)
  assert.equal(effects.group.visible,false)
})

const {createKitchenAssembly}=await load('kitchenAssembly')
const {IndoorSmoke}=await load('indoorSmoke')
const {kitchenWindowWall}=await load('interiorArchitecture')

test('detailed kitchen keeps equipment within the frozen footprint and stove at its fire anchor',()=>{
  for(const [width,depth] of [[2.296,.64],[4.756,.8]]){
    const stoveX=width*.375, kitchen=createKitchenAssembly({width,depth,worktopHeight:.92,stoveX})
    const bounds=new THREE.Box3().setFromObject(kitchen)
    assert.ok(bounds.min.x>=-width/2-.001 && bounds.max.x<=width/2+.001,'No fittings may extend into an adjacent walking envelope')
    assert.ok(bounds.min.z>=-depth/2-.001 && bounds.max.z<=depth/2+.001)
    assert.ok(bounds.min.y>=-1e-6 && bounds.max.y<=2.1, JSON.stringify({min:bounds.min.toArray(),max:bounds.max.toArray()}))
    assert.ok(Math.abs(kitchen.getObjectByName('cooktop-glass').position.x-stoveX)<1e-8)
    const opening=new THREE.Vector3(-width/8,.92,0)
    const ray=new THREE.Raycaster(opening.clone().add(new THREE.Vector3(0,.5,0)),new THREE.Vector3(0,-1,0),0,.8)
    kitchen.updateMatrixWorld(true)
    const hits=ray.intersectObject(kitchen,true)
    assert.ok(hits.some(hit=>hit.object.name==='sink-basin'),'Sink opening must expose a recessed basin')
    assert.ok(hits[0].point.y<.82,'Static batching must not fill the sink cavity')
    assert.ok(!hits.some(hit=>hit.object.name.startsWith('sink-rim')),'Sink hole must remain physically open')
    const frontRay=new THREE.Raycaster(new THREE.Vector3(stoveX,.92*.45,depth),new THREE.Vector3(0,0,-1))
    assert.equal(frontRay.intersectObject(kitchen,true)[0].object.name,'oven-glass','A solid cabinet front must not hide the oven')
  }
})

test('kitchen window is an opening in the wall, not glazing over an opaque box',()=>{
  const wall=kitchenWindowWall(2.8,3.2,{surface:()=>new THREE.MeshStandardMaterial()})
  wall.updateMatrixWorld(true)
  const ray=new THREE.Raycaster(new THREE.Vector3(-2.8*.103+.1,1.6,0),new THREE.Vector3(0,0,-1))
  const hits=ray.intersectObject(wall,true)
  assert.ok(hits.some(hit=>hit.object.name==='window-glass'))
  assert.ok(!hits.some(hit=>hit.object.name.startsWith('window-wall')))
})

test('room camera includes equipment height on desktop and phone without cutting the room corners',()=>{
  const room={x:4,y:3,width:2.8,depth:3.2,height:6.58}
  for(const aspect of [2,.46]){
    const frame=kitchenCamera(room,aspect),camera=new THREE.PerspectiveCamera(48,aspect,.1,400)
    camera.position.copy(frame.position);camera.lookAt(frame.target);camera.updateMatrixWorld(true)
    for(const x of [-1.4,1.4])for(const y of [0,2.7])for(const z of [-1.6,1.6]){
      const p=new THREE.Vector3(room.x+x,room.height+y,room.y+z).project(camera)
      assert.ok(Math.abs(p.x)<1 && Math.abs(p.y)<1)
    }
  }
})

test('smoke visual stays inside each zone and reduces instances in low quality',()=>{
  const smoke=new IndoorSmoke(1.2,3.2,17)
  smoke.update(.7,130);assert.equal(smoke.mesh.visible,true)
  for(const quality of [1,.45]){
    smoke.step(40,quality);assert.equal(smoke.mesh.count,quality===1?32:12)
    for(let i=0;i<smoke.mesh.count;i++){
      const matrix=new THREE.Matrix4(),position=new THREE.Vector3(),rotation=new THREE.Quaternion(),scale=new THREE.Vector3()
      smoke.mesh.getMatrixAt(i,matrix);matrix.decompose(position,rotation,scale)
      assert.ok(Math.abs(position.x)+scale.x<=.6+.00001 && Math.abs(position.z)+scale.z<=1.6+.00001)
    }
  }
  smoke.update(0,25);assert.equal(smoke.mesh.visible,false)
})

const {stairSurface,stairHeight,createStairFlight}=await load('stairFlight')
const {plantFoot}=await load('footPlacement')
const {VisualClock}=await load('visualClock')

test('stair meshes, downward flights and foot support share the same solid tread heights',()=>{
  const low=new THREE.Vector3(1,.18,2),high=new THREE.Vector3(1,3.38,6)
  const surface=stairSurface(high,low,1.2),flight=createStairFlight(surface)
  flight.group.updateMatrixWorld(true)
  for(const t of [.07,.33,.79]){
    const z=2+t*4,expected=stairHeight(surface,1,z,.18+t*3.2)
    const ray=new THREE.Raycaster(new THREE.Vector3(1,5,z),new THREE.Vector3(0,-1,0))
    const hit=ray.intersectObject(flight.group,true).find(hit=>hit.object.name==='solid-stair-treads')
    assert.ok(hit&&Math.abs(hit.point.y-expected)<1e-5)
  }
  assert.equal(stairHeight(surface,1,6,3.38),3.38)
  assert.equal(stairHeight(surface,3,4,1.78),undefined,'A foot outside the actual flight must not snap to a stair')
  assert.equal(stairHeight(surface,1,4,8),undefined,'Another floor is not the walking surface')
})

test('foot placement preserves the authoritative root and leg lengths while clearing a tread',()=>{
  const root=new THREE.Group();root.position.set(3,0,5);root.rotation.y=.7
  const hip=new THREE.Bone(),knee=new THREE.Bone(),foot=new THREE.Bone()
  hip.position.y=1;knee.position.set(0,-.4,.15);foot.position.set(0,-.45,-.15)
  root.add(hip);hip.add(knee);knee.add(foot);root.updateMatrixWorld(true)
  const position=root.position.clone(),upper=hip.getWorldPosition(new THREE.Vector3()).distanceTo(knee.getWorldPosition(new THREE.Vector3())),lower=knee.getWorldPosition(new THREE.Vector3()).distanceTo(foot.getWorldPosition(new THREE.Vector3()))
  const rotation=foot.getWorldQuaternion(new THREE.Quaternion())
  assert.equal(plantFoot({hip,knee,foot},.26),true)
  assert.ok(Math.abs(foot.getWorldPosition(new THREE.Vector3()).y-.26)<1e-5)
  assert.ok(root.position.equals(position))
  assert.ok(Math.abs(upper-hip.getWorldPosition(new THREE.Vector3()).distanceTo(knee.getWorldPosition(new THREE.Vector3())))<1e-5)
  assert.ok(Math.abs(lower-knee.getWorldPosition(new THREE.Vector3()).distanceTo(foot.getWorldPosition(new THREE.Vector3())))<1e-5)
  assert.ok(Math.abs(rotation.dot(foot.getWorldQuaternion(new THREE.Quaternion())))>1-1e-6)
})

test('indoor flames stay above the burner and below the ceiling from tilted cameras',()=>{
  const effects=new FireEffects(),camera=new THREE.PerspectiveCamera()
  camera.position.set(2,5,3);camera.lookAt(0,0,0);camera.updateMatrixWorld(true)
  const bounds={width:.5,depth:.65,height:.8},matrix=new THREE.Matrix4()
  for(const seconds of [0,4.2,31]){
    effects.update(seconds,100,8,'微风',camera,1,true,bounds)
    const flame=effects.group.children[0]
    assert.equal(effects.group.children[1].visible,false)
    for(let i=0;i<flame.count;i++){
      flame.getMatrixAt(i,matrix)
      for(const x of [-.5,.5])for(const y of [-.5,.5]){
        const corner=new THREE.Vector3(x,y,0).applyMatrix4(matrix)
        assert.ok(Math.abs(corner.x)<=bounds.width/2+1e-6&&Math.abs(corner.z)<=bounds.depth/2+1e-6)
        assert.ok(corner.y>=0&&corner.y<=bounds.height+1e-6)
      }
    }
  }
})

test('smoke remains beneath the ceiling and replay effects use exact historical time',()=>{
  const smoke=new IndoorSmoke(2.8,3.2,7),matrix=new THREE.Matrix4()
  for(const density of [.01,.5,1]){
    smoke.update(density,45);smoke.step(80)
    for(let i=0;i<smoke.mesh.count;i++){
      smoke.mesh.getMatrixAt(i,matrix)
      const p=new THREE.Vector3(),s=new THREE.Vector3();matrix.decompose(p,new THREE.Quaternion(),s)
      assert.ok(p.y+s.y<=2.42+1e-6&&p.y-s.y>=1.1)
    }
  }
  const clock=new VisualClock()
  assert.equal(clock.at(5,true,1000),5);assert.equal(clock.at(5,true,1200),5.2)
  assert.equal(clock.at(5,true,6000),5.5);assert.equal(clock.at(5,false,6100),5)
  assert.equal(clock.at(2,false,6200),2)
})

test('fallback robot keeps a compact footprint when detailed assets are unavailable',()=>{
  const bounds=new THREE.Box3().setFromObject(createPatrolRobot()),size=bounds.getSize(new THREE.Vector3())
  assert.ok(size.x<=.72&&size.z<=1.08&&size.y<=1.2)
})

const {ResidentialDoor}=await load('residentialDoor')
const {createStreet}=await load('communityModels')
const {ROAD_SURFACE_Y}=await load('roadSurface')
const {fitVehicleModel,poseVehicleWheels,poseAmbulanceRearDoors}=await load('vehicleModel')
const {createGasValve}=await load('gasValve')
const {createStretcher,poseStretcher}=await load('stretcherModel')
const {routeHeading}=await load('routeHeading')
const {RescueVisuals}=await load('rescueVisuals')
const {roadJunctions,createJunctionPatch,alignRoadTexture}=await load('roadJunctions')

test('shared road endpoints fill outer turn gaps without inventing crossing nodes',()=>{
  const road=(id,start,end)=>({id,start,end,width_meters:4,status:'open',risk_score:0,name:id})
  const a=road('west',{x:40,y:50},{x:50,y:50}),b=road('south',{x:50,y:50},{x:50,y:60})
  const {patches,cuts}=roadJunctions([a,b])
  assert.equal(patches.length,1)
  const patch=createJunctionPatch(patches[0],new THREE.MeshBasicMaterial())
  patch.updateMatrixWorld(true)
  const ray=new THREE.Raycaster(new THREE.Vector3(.7,2,-.7),new THREE.Vector3(0,-1,0))
  assert.ok(ray.intersectObject(patch).length>0,'The outer elbow gap must have an actual upward-facing surface')
  assert.ok(cuts.get('west').end>=2&&cuts.get('south').start>=2)
  assert.equal(roadJunctions([a,road('cross',{x:45,y:40},{x:45,y:60})]).patches.length,0)
  assert.equal(roadJunctions([{...a,end:{...a.end,id:'upper'}},{...b,start:{...b.start,id:'lower'}}]).patches.length,0,'Distinct frozen nodes at one coordinate must not be joined visually')
})

test('asphalt UVs agree at the same world point across rotated road pieces',()=>{
  const a=new THREE.Mesh(new THREE.PlaneGeometry(4,10)),b=new THREE.Mesh(new THREE.PlaneGeometry(10,4))
  a.rotation.x=b.rotation.x=-Math.PI/2;b.rotation.z=Math.PI/2
  a.position.set(3,.008,5);b.position.copy(a.position)
  for(const mesh of [a,b]){
    alignRoadTexture(mesh)
    const p=new THREE.Vector3().fromBufferAttribute(mesh.geometry.attributes.position,0).applyMatrix4(mesh.matrixWorld)
    const uv=mesh.geometry.attributes.uv
    assert.ok(Math.abs(uv.getX(0)-p.x/3)<1e-6&&Math.abs(uv.getY(0)-p.z/3)<1e-6)
  }
})

test('acute junctions reserve curb clearance and narrow alleys have no centre line',()=>{
  const edges=[{id:'a',start:{x:40,y:50},end:{x:50,y:50},width_meters:4},
    {id:'b',start:{x:50,y:50},end:{x:40,y:51},width_meters:4}]
  const cuts=roadJunctions(edges).cuts
  assert.ok(cuts.get('a').end>10,'A very acute junction must not retain a curb across the other road')
  const street=createStreet(10,1.2,undefined,{start:2,end:2})
  const marking=street.children.find(o=>o.isInstancedMesh&&o.geometry.parameters.depth===1.5)
  assert.equal(marking.count,0)
  const roads=new RoadVisuals()
  roads.update([{...edges[0],end:edges[0].start,status:'open',risk_score:0,name:'empty'}],()=> '')
  assert.equal(roads.meshes.size,0)
  roads.dispose()
})

test('detailed doors seal the transom and park both handles outside the frozen aperture',()=>{
  const door=new ResidentialDoor(.9,.28,.1)
  door.setOpen(false);door.frame.updateMatrixWorld(true)
  const header=new THREE.Raycaster(new THREE.Vector3(0,2.33,1),new THREE.Vector3(0,0,-1))
  assert.ok(header.intersectObject(door.frame,true).length>0,'A closed compartment must not have an unmodelled hole above its frame')
  door.setOpen(true);door.frame.updateMatrixWorld(true)
  assert.ok(new THREE.Box3().setFromObject(door.leaf).max.x<-.45)
  const opening=new THREE.Raycaster(new THREE.Vector3(0,1,1),new THREE.Vector3(0,0,-1))
  assert.equal(opening.intersectObject(door.frame,true).length,0,'The declared doorway width must stay clear')
  door.setOpen(false);door.step(.1,true);assert.ok(door.leaf.rotation.y>0&&door.leaf.rotation.y<Math.PI/2)
  door.step(0,false);assert.equal(door.leaf.rotation.y,0,'Paused/history frames settle directly to authority')
  door.setOpen(true);assert.equal(door.leaf.rotation.y,Math.PI/2,'An accepted opening must not obstruct a person already allowed through')
})

test('narrow streets and risk geometry preserve the configured physical width',()=>{
  const street=createStreet(12,1.2)
  const bounds=new THREE.Box3().setFromObject(street)
  assert.ok(bounds.max.x-bounds.min.x<=1.2+1e-6)
  const surface=street.children[0]
  assert.ok(Math.abs(surface.position.y+surface.geometry.parameters.height/2-ROAD_SURFACE_Y)<1e-6)
  const roads=new RoadVisuals()
  roads.update([{id:'narrow',name:'窄巷',start:{x:0,y:0},end:{x:0,y:12},width_meters:1.2,status:'open',risk_score:0}],()=> '')
  assert.ok(roads.meshes.get('narrow').geometry.parameters.width<=1.2)
  assert.ok(roads.meshes.get('narrow').position.y<.05,'Risk projections must not float at ankle height')
  roads.dispose()
})

test('vehicle fitting faces the authored front toward motion and wheels do not change the root',()=>{
  const model=new THREE.Group();model.position.set(3,0,8)
  const body=new THREE.Mesh(new THREE.BoxGeometry(1.2,1,3));body.position.y=.8;model.add(body)
  for(const front of [true,false])for(const side of [-1,1]){
    const wheel=new THREE.Mesh(new THREE.BoxGeometry(.1,.6,.6));wheel.name='wheel-'+(front?'front':'back')+'-'+side
    wheel.position.set(side*.55,.3,front?.9:-.9);model.add(wheel)
  }
  const wheels=fitVehicleModel(model,6.2,2.45),bounds=new THREE.Box3().setFromObject(model),size=bounds.getSize(new THREE.Vector3())
  assert.ok(size.z<=6.2+1e-6&&size.x<=2.45+1e-6&&Math.abs(bounds.min.y)<1e-6)
  assert.ok(Math.abs(bounds.getCenter(new THREE.Vector3()).x)<1e-6&&Math.abs(bounds.getCenter(new THREE.Vector3()).z)<1e-6)
  const front=wheels.find(w=>w.front).object.getWorldPosition(new THREE.Vector3()),back=wheels.find(w=>!w.front).object.getWorldPosition(new THREE.Vector3())
  assert.ok(front.z<back.z,'The vehicle must drive forwards, not tail first')
  const rootRotation=model.quaternion.clone(),position=model.position.clone()
  poseVehicleWheels(wheels,.8,.2)
  assert.ok(wheels.every(w=>w.object.userData.wheelRoll>0))
  assert.ok(model.position.equals(position)&&model.quaternion.equals(rootRotation))
  assert.throws(()=>fitVehicleModel(new THREE.Group(),6.2,2.45),/有效三维尺寸/)
})

test('packaged ambulance rear leaves open from their own hinges during boarding',async()=>{
  const glb=await readFile(new URL('../public/assets/kenney-car-kit/ambulance.glb',import.meta.url))
  const scene=JSON.parse(glb.subarray(20,20+glb.readUInt32LE(12)).toString('utf8'))
  const rear=scene.nodes.filter(node=>node.name==='door-left'||node.name==='door-right')
  assert.equal(rear.length,2,'The delivered ambulance asset must have two separate rear leaves')
  const model=new THREE.Group()
  for(const node of rear){const leaf=new THREE.Group();leaf.name=node.name;model.add(leaf)}
  assert.ok(poseAmbulanceRearDoors(model,1))
  assert.ok(model.getObjectByName('door-left').rotation.y<0)
  assert.ok(model.getObjectByName('door-right').rotation.y>0)
  poseAmbulanceRearDoors(model,0)
  assert.ok(Math.abs(model.getObjectByName('door-left').rotation.y)<1e-8)
  assert.ok(Math.abs(model.getObjectByName('door-right').rotation.y)<1e-8)
})

test('gas hardware stays inside the counter depth and stops below the hood',()=>{
  for(const depth of [.224,.64,.8]){
    const valve=createGasValve(depth),bounds=new THREE.Box3().setFromObject(valve.group)
    assert.ok(bounds.min.z>=-depth/2-1e-6&&bounds.max.z<=depth/2+1e-6)
    assert.ok(bounds.max.y<.36,'A pipe must not continue into the hood above the valve')
    assert.equal(valve.handle.name,'gas-isolation-lever')
  }
})

test('stretcher crew, gait and equipment fit the route profile without moving its root',()=>{
  const root=createStretcher();root.position.y=.014
  const position=root.position.clone(),rotation=root.quaternion.clone()
  for(const seconds of [0,.2,.6,1,3]){
    poseStretcher(root,.08,seconds,true)
    const bounds=new THREE.Box3().setFromObject(root)
    assert.ok(bounds.min.x>=-.4&&bounds.max.x<=.4,'Equipment must fit an 0.8 m assembly connector')
    assert.ok(bounds.min.z>=-2&&bounds.max.z<=2,'Walking feet are part of the crew envelope')
    // A rotated wheel's bounding box encloses empty corners below its circular
    // tread. Inspect actual surface vertices rather than that loose box.
    let ground=Infinity
    root.traverse(object=>{
      const vertices=object.geometry?.attributes.position
      if(vertices)for(let index=0;index<vertices.count;index++)ground=Math.min(ground,new THREE.Vector3().fromBufferAttribute(vertices,index).applyMatrix4(object.matrixWorld).y)
    })
    assert.ok(ground>=-1e-6,`Castors and rescuers stand on the same ground: ${ground}`)
    assert.ok(root.position.equals(position)&&root.quaternion.equals(rotation))
    for(const helper of root.userData.helpers){
      assert.equal(helper.userData.limbs[0].rotation.x,helper.userData.stretcherEnd*.5)
      assert.equal(helper.userData.limbs[2].rotation.x,helper.userData.stretcherEnd*.5)
    }
  }
  assert.ok(root.userData.wheels.every(wheel=>wheel.userData.roll!==0))
  for(const name of ['restraint-strap','strap-buckle','raised-side-rail','pillow'])assert.ok(root.getObjectByName(name))
})

test('historical heading follows the confirmed segment and ignores disconnected routes',()=>{
  const route=[new THREE.Vector3(0,0,0),new THREE.Vector3(10,0,0),new THREE.Vector3(10,0,10)]
  assert.equal(routeHeading(new THREE.Vector3(5,0,0),route),-Math.PI/2)
  assert.equal(routeHeading(new THREE.Vector3(10,0,5),route),-Math.PI)
  assert.equal(routeHeading(new THREE.Vector3(8,0,6),route),undefined)
  assert.equal(routeHeading(new THREE.Vector3(),[new THREE.Vector3(),new THREE.Vector3()]),undefined)
})

test('pickup crew meets the waiting resident and historical views use the actual crew position',()=>{
  const visuals=new RescueVisuals(()=>{})
  const action={action_id:'pickup-1',action:'load',resident_id:'r1',starts_at_seconds:0,approach_seconds:4,duration_seconds:16,remaining_seconds:14,
    pickup_points:[{x:28,y:25},{x:25,y:25}],reason:'担架组正前往集合点接人'}
  const vehicle={id:'a1',x:25,y:25,service:action}
  const resident={id:'r1',label:'居民1',x:28,y:25,medical_transfer:{phase:'pickup',vehicle_id:'a1'}}
  visuals.update([vehicle],[resident],2,false)
  const root=visuals.layer.getObjectByName('medical-stretcher-team')
  assert.ok(Math.abs(root.position.x+23.5)<1e-6)
  assert.equal(root.rotation.y,-Math.PI/2)
  assert.equal(root.userData.patient.visible,false,'The waiting resident is not simultaneously shown on an empty approaching stretcher')
  assert.equal(root.userData.selection.x,26.5,'Inspecting the crew must locate the crew, not its future destination')
  visuals.update([{...vehicle,service:{...action,action_id:'pickup-2'}}],[{...resident,x:27,medical_transfer:{phase:'loading',vehicle_id:'a1'}}],6,false)
  assert.equal(root.userData.patient.visible,true)
  assert.equal(root.position.x,-23)
  visuals.update([{...vehicle,service:null}],[resident],16,false)
  assert.equal(root.visible,false)
  visuals.dispose()
})

test('confirmed boarding folds the carriage while helpers remain beside the vehicle',()=>{
  const visuals=new RescueVisuals(()=>{})
  const action={action_id:'boarding-1',action:'load',resident_id:'r1',starts_at_seconds:0,approach_seconds:4,
    duration_seconds:16,ends_at_seconds:16,remaining_seconds:4,
    pickup_points:[{x:30,y:25},{x:28,y:25}],loading_position:{x:28,y:25},boarding_position:{x:25,y:25},reason:'车边装载'}
  const vehicle={id:'a1',x:25,y:25,service:action}
  const resident={id:'r1',label:'居民1',x:26.5,y:25,medical_transfer:{phase:'boarding',vehicle_id:'a1'}}
  visuals.update([vehicle],[resident],12,false)
  const root=visuals.layer.getObjectByName('medical-stretcher-team')
  assert.equal(root.userData.boarding,.5)
  assert.ok(root.userData.carriage.position.length()>1)
  assert.ok(root.userData.helpers.every(helper=>helper.parent===root))
  visuals.step(.016,false,12,true)
  const leg=root.getObjectByName('folding-leg')
  assert.ok(leg.scale.y<1,'The confirmed boarding phase must physically fold the stretcher legs')
  visuals.dispose()
})

test('water effects freeze at historical drill time and stopped actions release their meshes',()=>{
  const visuals=new RescueVisuals(()=>{}),action={action_id:'spray-1',action:'spray',remaining_seconds:30,target:{x:40,y:25},water_source:{x:24,y:25}}
  visuals.update([{id:'f1',x:25,y:25,service:action}],[],12,false)
  visuals.step(.016,false,200,true)
  const drops=visuals.layer.children[0].children.find(object=>object.isInstancedMesh),matrix=new THREE.Matrix4()
  drops.getMatrixAt(0,matrix);const frozen=matrix.clone()
  visuals.step(.016,false,1000,true);drops.getMatrixAt(0,matrix)
  assert.ok(matrix.equals(frozen),'Paused water must not advance with wall time or reset to its start')
  let disposed=false;drops.geometry.addEventListener('dispose',()=>{disposed=true})
  visuals.update([{id:'f1',x:25,y:25,service:null}],[],13,false)
  assert.equal(visuals.layer.children.length,0)
  assert.equal(disposed,true)
  visuals.dispose()
})
