import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import ts from 'typescript'
import * as THREE from 'three'

const require=createRequire(import.meta.url)
const threeUrl=pathToFileURL(require.resolve('three').replace(/three\.cjs$/,'three.module.js')).href
const source=await readFile(new URL('../src/three/kitchenAssets.ts',import.meta.url),'utf8')
const compiled=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText
const code=compiled.replace(/from ['"]three['"]/g,`from '${threeUrl}'`)
  .replace(/import \{ GLTFLoader \} from [^;]+;/,'const GLTFLoader = globalThis.__kitchenTestLoader;')
globalThis.__kitchenTestLoader=class { async parseAsync() {
  const scene=new THREE.Group();scene.add(new THREE.Mesh(new THREE.BoxGeometry(1,1,1),new THREE.MeshStandardMaterial()))
  return {scene}
} }
const {KitchenAssets}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'))
delete globalThis.__kitchenTestLoader

test('all shipped kitchen GLBs are self-contained and have renderable meshes',async()=>{
 for(const name of ['kitchenFridge','kitchenSink','kitchenCabinetDrawer','kitchenStove','kitchenCabinetUpper']) {
  const data=await readFile(new URL(`../public/assets/kitchen/${name}.glb`,import.meta.url))
  assert.equal(data.toString('ascii',0,4),'glTF')
  assert.equal(data.readUInt32LE(4),2)
  assert.equal(data.readUInt32LE(8),data.length)
  const json=JSON.parse(data.toString('utf8',20,20+data.readUInt32LE(12)).trim())
  assert.ok(json.meshes?.length>0,name)
  for(const item of [...json.buffers??[],...json.images??[]]) assert.ok(!item.uri||item.uri.startsWith('data:'),`${name} needs external ${item.uri}`)
 }
})

test('failed kitchen asset can retry; successful clones share one download and stay within the footprint',async()=>{
 const realFetch=globalThis.fetch;let requests=0
 globalThis.fetch=async()=>++requests===1?new Response('',{status:503}):new Response(new ArrayBuffer(8))
 const assets=new KitchenAssets()
 try {
  await assert.rejects(assets.fit('kitchenStove',1,.9,.6))
  const a=await assets.fit('kitchenStove',1,.9,.6),b=await assets.fit('kitchenStove',1,.9,.6)
  assert.equal(requests,2);assert.notEqual(a,b)
  const bounds=new THREE.Box3().setFromObject(a),size=bounds.getSize(new THREE.Vector3())
  assert.ok(size.x<=1&&size.y<=.9&&size.z<=.6)
  assert.ok(Math.abs(bounds.min.y)<1e-6)
  await assert.rejects(assets.fit('kitchenStove',NaN,.9,.6))
  await assert.rejects(assets.fit('../remote',1,.9,.6))
  assert.equal(requests,2)
 } finally {assets.dispose();globalThis.fetch=realFetch}
})

test('closing a kitchen cancels unfinished model download and keeps late results detached',async()=>{
 const realFetch=globalThis.fetch;let aborted=false
 globalThis.fetch=(_url,{signal})=>new Promise((_resolve,reject)=>signal.addEventListener('abort',()=>{aborted=true;reject(new DOMException('closed','AbortError'))},{once:true}))
 const assets=new KitchenAssets()
 try {
  const pending=assets.fit('kitchenSink',1,1,1)
  assets.dispose()
  await assert.rejects(pending)
  assert.equal(aborted,true)
  assert.equal(await assets.fit('kitchenSink',1,1,1),null)
 } finally {assets.dispose();globalThis.fetch=realFetch}
})
