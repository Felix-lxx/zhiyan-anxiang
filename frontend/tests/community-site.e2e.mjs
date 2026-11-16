// Real local glTF dependencies under the application's CSP, including load failure.
import assert from 'node:assert/strict'
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright')
const browser=await chromium.launch({headless:true,...(process.env.QA_BROWSER_PATH?{executablePath:process.env.QA_BROWSER_PATH}:{})})
try {
  const page=await browser.newPage()
  const errors=[]
  page.on('pageerror',error=>errors.push(error.message))
  const url=(process.env.QA_BASE_URL||'http://127.0.0.1:5173')+'/tools/actors-preview.html'
  async function check(fail) {
    await page.goto(url)
    return page.evaluate(async fail=>{
      const THREE=await import('/node_modules/.vite/deps/three.js')
      const {CommunitySiteVisuals}=await import('/src/three/communitySiteVisuals.ts')
      const {SceneMaterials}=await import('/src/three/sceneMaterials.ts')
      const materials=new SceneMaterials()
      const site=new CommunitySiteVisuals({
        objects:[{type:'building',x:30,y:35,width:10,depth:12},{type:'building',x:70,y:70,width:10,depth:12}],
        roads:[{start:{x:50,y:0},end:{x:50,y:100},width_meters:7}],
        passages:[{start:{x:30,y:41},end:{x:50,y:41},width_meters:2}],
        protectedPoints:[{x:30,y:41,radius:2}],
      },materials,()=>{})
      const loaded=await site.load()
      site.group.updateMatrixWorld(true)
      const outside=[],counts={}
      const plans=new Map(site.plan.map(f=>[f.id,f]))
      function boundsFit(object,rect) {
        const b=new THREE.Box3().setFromObject(object),epsilon=.001
        return b.min.x>=rect.x-50-rect.width/2-epsilon&&b.max.x<=rect.x-50+rect.width/2+epsilon&&
          b.min.z>=rect.y-50-rect.depth/2-epsilon&&b.max.z<=rect.y-50+rect.depth/2+epsilon&&b.min.y>=-.001
      }
      site.group.traverse(object=>{
        counts[object.name]=(counts[object.name]||0)+1
        const rect=object.userData.siteFootprint||plans.get(object.userData.siteFeature)
        if(rect&&!boundsFit(object,rect))outside.push(object.name)
      })
      site.setQuality('low')
      const hiddenShrubs=[]
      site.group.traverse(object=>{
        if(object.name==='scanned-community-shrub')hiddenShrubs.push(object.parent.visible===false)
      })
      site.dispose();materials.dispose()
      return {fail,loaded,outside,counts,hiddenShrubs,remaining:site.group.children.length}
    },fail)
  }
  const ready=await check(false)
  assert.equal(ready.loaded.failed,0)
  assert.ok(ready.counts['scanned-community-bench']>0)
  assert.ok(ready.counts['scanned-community-shrub']>0)
  assert.ok(ready.counts['parked-community-car']>0)
  assert.deepEqual(ready.outside,[],'Imported meshes stay inside their reserved footprints')
  assert.ok(ready.hiddenShrubs.every(Boolean))
  assert.equal(ready.remaining,0)
  await page.route('**/assets/community-real/**',route=>route.abort())
  const fallback=await check(true)
  assert.equal(fallback.loaded.failed,2)
  assert.ok(fallback.counts['bench-fallback']>0)
  assert.deepEqual(fallback.outside,[])
  assert.equal(fallback.remaining,0)
  assert.deepEqual(errors,[])
  console.log(JSON.stringify({ready,fallback}))
} finally {await browser.close()}
