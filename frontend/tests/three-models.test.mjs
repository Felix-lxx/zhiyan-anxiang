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
