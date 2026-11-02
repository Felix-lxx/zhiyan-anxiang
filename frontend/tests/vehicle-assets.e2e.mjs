// Production loaders under the application's CSP; no replacement model responses.
import assert from 'node:assert/strict'
const {default:playwright}=await import(process.env.PLAYWRIGHT_MODULE||'playwright')
const browser=await playwright.chromium.launch({headless:true,...(process.env.QA_BROWSER_PATH?{executablePath:process.env.QA_BROWSER_PATH}:{})})
try {
  const page=await browser.newPage();page.setDefaultTimeout(25000)
  const errors=[];page.on('pageerror',error=>errors.push(error.message))
  await page.goto((process.env.QA_BASE_URL||'http://127.0.0.1:5181')+'/tests/kitchen-director.html')
  await page.locator('.twin-stage canvas').waitFor()
  await page.route('**/kenney-car-kit/Textures/colormap.png',route=>route.abort())
  await page.evaluate(async()=>{
    window.__vehiclePolicyViolations=[]
    document.addEventListener('securitypolicyviolation',event=>window.__vehiclePolicyViolations.push(event.effectiveDirective))
    const {VehicleVisuals}=await import('/src/three/vehicleVisuals.ts')
    const visuals=new VehicleVisuals(()=>{},()=>{})
    const base={x:25,y:25,state:'arrived',reason:'隔离资源检查',target_name:'',target_node_id:null,mission_id:null,current_edge_id:null,progress:1,remaining_seconds:null,route_points:[{x:20,y:25},{x:25,y:25}],route_edge_ids:[],heading_radians:-Math.PI/2}
    const data=[{...base,id:'firetruck',name:'消防车',kind:'firetruck',minimum_width:3.5},{...base,id:'ambulance',name:'救护车',kind:'ambulance',minimum_width:2.8}]
    window.__vehicleAssetCheck={visuals,data};visuals.update(data,20,false)
  })
  await page.waitForFunction(()=>window.__vehicleAssetCheck.visuals.loadingCount===0)
  assert.equal(await page.evaluate(()=>window.__vehicleAssetCheck.visuals.failedCount),2)
  await page.unroute('**/kenney-car-kit/Textures/colormap.png')
  await page.evaluate(()=>window.__vehicleAssetCheck.visuals.retryFailed())
  const result=await page.evaluate(()=>{
    const {visuals,data}=window.__vehicleAssetCheck
    const records=[...visuals.models.values()].map(root=>{
      let mapped=true,count=0
      root.userData.body.traverse(mesh=>{
        if(!mesh.isMesh)return
        for(const material of Array.isArray(mesh.material)?mesh.material:[mesh.material]){count++;mapped=mapped&&material.map?.image?.width>0}
      })
      return {status:root.userData.assetStatus,mapped,count,heading:root.rotation.y}
    })
    visuals.update(data.map(v=>({...v,heading_radians:0})),19,false)
    const replay=[...visuals.models.values()].map(root=>root.rotation.y)
    visuals.dispose()
    return {records,replay,violations:window.__vehiclePolicyViolations}
  })
  assert.ok(result.records.every(record=>record.status==='ready'&&record.mapped&&record.count>0&&record.heading===-Math.PI/2))
  assert.deepEqual(result.replay,[0,0])
  assert.deepEqual(result.violations,[])
  assert.deepEqual(errors,[])
  console.log(JSON.stringify({checks:['本地颜色纹理','纹理失败回退与重试','现有CSP下加载','暂停与回放朝向'],...result}))
} finally { await browser.close() }
