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
async function load(name) {
  const source = await readFile(new URL('../src/three/' + name + '.ts', import.meta.url), 'utf8')
  const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } })
  return import('data:text/javascript;base64,' + Buffer.from(outputText.replace(/from ['"]three['"]/g, `from '${threeUrl}'`)).toString('base64'))
}
const { displayHeight } = await load('sceneMaterials')
const { createPerson, posePerson, createPatrolRobot } = await load('actors')
const { RoadVisuals } = await load('roadVisuals')
const { CrowdRenderer } = await load('crowdRenderer')
const { presentHelpers, meetingRoute } = await load('helperPresentation')
const { createRouteGuide } = await load('routeGuide')

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
