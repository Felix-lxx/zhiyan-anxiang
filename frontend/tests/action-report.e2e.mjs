// Actual isolated API, authoritative clock and production task/3D components.
import assert from 'node:assert/strict'
import {mkdirSync,writeFileSync} from 'node:fs'
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright')
assert.ok(process.env.QA_PASSWORD,'Use an isolated QA database and account')
const base=process.env.QA_BASE_URL||'http://127.0.0.1:5203'
const api=process.env.QA_API_URL||'http://127.0.0.1:8041/api/v1'
const output='../output/playwright/action-report';mkdirSync(output,{recursive:true})
const browser=await chromium.launch({headless:true,...(process.env.QA_BROWSER_PATH?{executablePath:process.env.QA_BROWSER_PATH}:{})})
const context=await browser.newContext(),page=await context.newPage()
const errors=[];page.on('pageerror',e=>errors.push(e.message))
let headers={},root
async function request(path,data,method=data===undefined?'GET':'POST'){
  const response=await context.request.fetch(api+path,{method,headers,...(data===undefined?{}:{data})})
  assert.ok(response.ok(),`${path}: ${response.status()}`)
  return response.json()
}
try{
  const auth=await request('/auth/login',{username:'admin',password:process.env.QA_PASSWORD})
  headers={Authorization:'Bearer '+auth.access_token}
  const community=await request('/communities/demo',{})
  const template=(await request('/scene-templates')).find(t=>t.code==='kitchen_fire')
  const scene=await request(`/communities/${community.id}/scenes`,{template_id:template.id,name:'夜班厨房责任作业验证'})
  const source=(await request(`/scenes/${scene.id}/fire-sources`))[0]
  await request(`/scenes/${scene.id}/parameters`,{...scene.versions.at(-1).parameters,
    fire_source_object_id:source.id,fire_source_type:'kitchen',fire_floor:2,fire_room:'east',
    resident_count:12,community_profile:'night_shift',duty_staff_count:2,room_door_state:'open',
    hydrant_status:'available',south_lane_status:'open',stair_width:1.2,start_time:'16:30'},'PATCH')
  await request(`/scenes/${scene.id}/publish`,{})
  const drill=await request(`/scenes/${scene.id}/drills`,{name:'动作报告与核验分离',training_mode:'teaching',time_scale:1})
  root='/drills/'+drill.id
  await request(root+'/state',{action:'start'},'PATCH')
  await page.goto(`${base}/communities/${community.id}/operations?scene=${scene.id}&drill=${drill.id}`)
  const close=page.getByRole('button',{name:'关闭面板',exact:true});if(await close.isVisible())await close.click()
  await page.getByRole('button',{name:'打开处置任务',exact:true}).click()
  const gas=drill.tasks.find(t=>t.kind==='gas_off')
  const workflow=page.locator('.task-workflow').filter({has:page.getByRole('heading',{name:gas.title,exact:true})})
  const accept=workflow.getByRole('button',{name:'总控代办此任务',exact:true})
  await accept.waitFor({timeout:60000});await accept.click()
  await workflow.getByRole('button',{name:'回执已到达目标',exact:true}).click()
  await workflow.locator('textarea').fill('现场已关闭燃气并核对阀门状态')
  const report=workflow.getByRole('button',{name:'报告动作完成',exact:true})
  await page.waitForFunction(()=>[...document.querySelectorAll('button')].some(b=>b.textContent==='报告动作完成'&&!b.disabled))
  const before=await request(root)
  assert.equal(before.simulation.environment.gas_off,false)
  await report.click()
  await workflow.getByRole('button',{name:'提交核验证据',exact:true}).waitFor()
  const reported=await request(root)
  assert.equal(reported.simulation.environment.gas_off,true)
  const indoor=reported.simulation.environment.indoor
  assert.ok(indoor.devices.length>0)
  assert.ok(indoor.devices.some(d=>d.room_id===indoor.source_zone_id&&d.state==='closed'))
  assert.equal(indoor.devices.find(d=>d.room_id===indoor.source_zone_id).basis,'task_action_report')
  assert.ok(indoor.devices.filter(d=>d.room_id!==indoor.source_zone_id).every(d=>d.state==='open'))
  assert.equal(reported.tasks.find(t=>t.id===gas.id).status,'verifying')
  assert.ok(!reported.simulation.environment.response_staff.some(s=>s.state==='task'))
  await page.reload()
  if(await close.isVisible())await close.click()
  if(!await workflow.isVisible())await page.getByRole('button',{name:'打开处置任务',exact:true}).click()
  await workflow.getByRole('button',{name:'提交核验证据',exact:true}).waitFor()
  await workflow.locator('textarea').fill('已核对动作报告与燃气阀门处置结果')
  for(const [width,height] of [[1440,900],[1366,650],[390,844]]){
    await page.setViewportSize({width,height})
    await workflow.getByRole('button',{name:'提交核验证据',exact:true}).scrollIntoViewIfNeeded()
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1))
    assert.ok(await workflow.evaluate(e=>e.scrollWidth<=e.clientWidth+1))
    await page.screenshot({path:`${output}/reported-${width}.png`})
  }
  await workflow.getByRole('button',{name:'提交核验证据',exact:true}).click()
  await workflow.getByText('已核验',{exact:true}).waitFor()
  assert.ok(await workflow.getByText(/^报告时刻 /).isVisible())
  const verified=await request(root)
  assert.equal(verified.tasks.find(t=>t.id===gas.id).status,'completed')
  const reportedTask=reported.tasks.find(t=>t.id===gas.id)
  const replay=await request(root+'/replay?at_seconds='+Math.max(0,reportedTask.action_reported_at-1))
  assert.equal(replay.simulation.environment.gas_off,false)
  assert.deepEqual(errors,[])
  const result={drillId:drill.id,reportedAt:reported.elapsed_seconds,verifiedAt:verified.elapsed_seconds,
    checks:['gas changed before verification','worker released','device state synchronized','historical state preserved','three viewport layouts'],pageErrors:errors}
  writeFileSync(output+'/result.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result))
}catch(error){await page.screenshot({path:output+'/failure.png'}).catch(()=>{});throw error}
finally{if(root)await request(root+'/state',{action:'pause'},'PATCH').catch(()=>{});await browser.close()}
