import test from 'node:test'
import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'
import {createHash} from 'node:crypto'
import ts from 'typescript'
import * as THREE from 'three'
import {pathToFileURL} from 'node:url'
import {createRequire} from 'node:module'

const require=createRequire(import.meta.url)
const threeUrl=pathToFileURL(require.resolve('three').replace(/three\.cjs$/,'three.module.js')).href
async function load(name){
  const source=await readFile(new URL('../src/three/'+name+'.ts',import.meta.url),'utf8')
  const code=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText.replace(/from ['"]three['"]/g,`from '${threeUrl}'`)
  return import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'))
}
const {SiteClearance,planCommunitySite}=await load('communitySite')
const {fitSiteAsset}=await load('siteAssetFit')
const {uncoveredDeck,createPassageDeck}=await load('passageDeck')

test('route decks subtract owned floor surfaces instead of rendering coplanar slabs',()=>{
  const start={x:-5,y:0},end={x:5,y:0}
  const polygons=uncoveredDeck(start,end,2,[{x:0,y:0,width:4,depth:4}])
  const area=polygons.reduce((sum,p)=>sum+Math.abs(p.reduce((a,v,i)=>{
    const n=p[(i+1)%p.length];return a+v.x*n.y-n.x*v.y
  },0))/2,0)
  assert.ok(Math.abs(area-12)<1e-8,'Only the uncovered 6m of the 2m-wide strip remains')
  assert.deepEqual(uncoveredDeck(start,end,2,[{x:0,y:0,width:20,depth:20}]),[])
  const a=new THREE.Vector3(-5,3.38,0),b=new THREE.Vector3(5,3.38,0)
  const deck=createPassageDeck(a,b,2,[{x:0,y:0,width:4,depth:4}],new THREE.MeshStandardMaterial())
  const bounds=new THREE.Box3().setFromObject(deck)
  assert.ok(Math.abs(bounds.max.y-3.38)<1e-6,'Uncovered thresholds retain the authoritative walking height')
  assert.equal(a.y,3.38);assert.equal(b.y,3.38)
})

test('site context respects buildings, door approaches, diagonal paths and other planned solids',()=>{
  const input={objects:[{type:'building',x:28,y:28,width:8,depth:6}],
    roads:[{start:{x:50,y:0},end:{x:50,y:100},width_meters:8}],
    passages:[{start:{x:12,y:20},end:{x:44,y:26},width_meters:1.8}],
    protectedPoints:[{x:28,y:32,radius:3}]}
  const before=structuredClone(input),plan=planCommunitySite(input)
  assert.ok(plan.some(f=>f.kind==='garden'))
  const validation=new SiteClearance(input)
  for(const feature of plan)assert.equal(validation.reserve(feature),true,feature.id)
  assert.deepEqual(input,before)
  assert.deepEqual(planCommunitySite(input),plan,'Loading order cannot change the layout')
})

test('malformed geometry and occupied communities omit decoration instead of forcing a placement',()=>{
  assert.deepEqual(planCommunitySite({objects:[{type:'building',x:NaN,y:30,width:8,depth:6}],roads:[]}),[])
  assert.deepEqual(planCommunitySite({objects:[],roads:[{start:{x:50,y:0},end:{x:50,y:100},width_meters:200}]}),[])
  const clearance=new SiteClearance({objects:[],roads:[]})
  assert.equal(clearance.fits({x:0,y:50,width:4,depth:4}),false)
  assert.equal(clearance.fits({x:30,y:30,width:-4,depth:4}),false)
})

test('imported asset fitting respects the whole footprint, ground and proportions without editing the source',()=>{
  const source=new THREE.Group(),mesh=new THREE.Mesh(new THREE.BoxGeometry(8,3,2),new THREE.MeshStandardMaterial())
  source.position.set(12,-3,4);source.rotation.y=.35;source.scale.set(1.1,.9,1.2);source.add(mesh)
  const before=source.matrix.clone(),position=source.position.clone()
  const model=fitSiteAsset(source,2.1,5.1,1.75,true)
  const bounds=new THREE.Box3().setFromObject(model),size=bounds.getSize(new THREE.Vector3())
  assert.ok(size.x<=2.1+1e-6&&size.z<=5.1+1e-6&&size.y<=1.75+1e-6)
  assert.ok(Math.abs(bounds.min.y)<1e-6)
  assert.ok(Math.abs(bounds.min.x+bounds.max.x)<1e-6&&Math.abs(bounds.min.z+bounds.max.z)<1e-6)
  assert.deepEqual(source.position,position)
  assert.ok(source.matrix.equals(before),'The shared prototype is not transformed by placement')
})

test('selected photographic assets match their recorded checksums and glTF dependencies remain local',async()=>{
  const root=new URL('../public/assets/',import.meta.url)
  const manifest=JSON.parse(await readFile(new URL('community-real/asset-manifest.json',root),'utf8'))
  assert.equal(manifest.license,'CC0-1.0')
  assert.equal(manifest.files.length,22)
  for(const entry of manifest.files){
    assert.ok(!entry.file.includes('..')&&!entry.file.startsWith('/'))
    const bytes=await readFile(new URL(entry.file,root))
    assert.equal(bytes.length,entry.bytes)
    assert.equal(createHash('sha256').update(bytes).digest('hex'),entry.sha256)
    if(!entry.file.endsWith('.gltf'))continue
    const gltf=JSON.parse(bytes.toString('utf8'))
    for(const part of [...gltf.buffers??[],...gltf.images??[]])if(part.uri){
      assert.ok(!/^(?:\w+:|\/)/.test(part.uri)&&!part.uri.includes('..'),'No CDN or escaping runtime dependency')
      await readFile(new URL(part.uri,new URL(entry.file,root)))
    }
  }
})
