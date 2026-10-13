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
