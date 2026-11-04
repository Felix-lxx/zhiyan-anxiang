// Explicit isolated database/API only. No paid provider or synthetic success.
import assert from 'node:assert/strict'
import {mkdirSync,writeFileSync} from 'node:fs'
import {randomUUID} from 'node:crypto'
const {default:playwright}=await import(process.env.PLAYWRIGHT_MODULE||'playwright')
const browser=await playwright.chromium.launch({headless:true,executablePath:process.env.QA_BROWSER_PATH})
const api=process.env.QA_API_URL||'http://127.0.0.1:8011/api/v1',base=process.env.QA_BASE_URL||'http://127.0.0.1:5181'
const out='../output/playwright/task-guidance-20261104';mkdirSync(out,{recursive:true})
let page,cleanup
try{
 const context=await browser.newContext();page=await context.newPage();page.setDefaultTimeout(20000)
 const errors=[],records=[];page.on('pageerror',e=>errors.push(e.message))
 const login=await context.request.post(api+'/auth/login',{data:{username:'admin',password:process.env.QA_PASSWORD}})
 assert.ok(login.ok());const headers={Authorization:'Bearer '+(await login.json()).access_token}
 const community=await(await context.request.post(api+'/communities/demo',{headers})).json()
 const template=(await(await context.request.get(api+'/scene-templates',{headers})).json()).find(item=>item.code==='kitchen_fire')
 assert.ok(template)
 const sceneResponse=await context.request.post(`${api}/communities/${community.id}/scenes`,{headers,data:{template_id:template.id,name:'UI 自动验收 · 任务依据厨房'}})
 assert.equal(sceneResponse.status(),201);const scene=await sceneResponse.json(),sceneRoot=api+'/scenes/'+scene.id
 const sources=await(await context.request.get(sceneRoot+'/fire-sources',{headers})).json();assert.ok(sources.length)
 const saved=await context.request.patch(sceneRoot+'/parameters',{headers,data:{fire_source_type:'kitchen',fire_source_object_id:sources[0].id,fire_floor:2,fire_room:'east',room_door_state:'closed',start_time:'18:30',wind_direction:'微风',resident_count:8,hydrant_status:'available',south_lane_status:'open',stair_width:1.2}})
 assert.ok(saved.ok(),await saved.text())
 const published=await context.request.post(sceneRoot+'/publish',{headers});assert.ok(published.ok(),await published.text())
 const result=await context.request.post(sceneRoot+'/drills',{headers,data:{name:'UI 自动验收 · 任务依据与设备定位',training_mode:'teaching',time_scale:1}})
 assert.equal(result.status(),201);const initial=await result.json(),root=api+'/drills/'+initial.id
 async function get(){const r=await context.request.get(root,{headers});assert.ok(r.ok());return r.json()}
 async function command(action){const r=await context.request.post(root+'/commands',{headers,data:{command_id:randomUUID(),kind:'state',arguments:{action}}});assert.ok(r.ok(),await r.text());return r.json()}
 cleanup=async()=>{if((await get()).status==='running')await command('pause')}
 const gas=initial.tasks.find(t=>t.kind==='gas_off');assert.ok(gas?.target_device_id)
 await command('start')
 const deadline=Date.now()+60000;let current
 while(Date.now()<deadline){current=await get();if(current.tasks.find(t=>t.id===gas.id)?.status==='pending')break;await new Promise(resolve=>setTimeout(resolve,1200))}
 assert.equal(current.tasks.find(t=>t.id===gas.id).status,'pending')
 const plan=await context.request.post(root+'/agent/runs',{headers,data:{request_id:randomUUID(),goal:'组织厨房楼栋居民撤离并核验案例任务',include_case_tasks:true,pause_for_review:true,use_model:false}})
 assert.equal(plan.status(),201,await plan.text());const run=await plan.json()
 assert.equal(run.task_graph.case_tasks.length,4)
 const url=`${base}/communities/${community.id}/operations?scene=${scene.id}&drill=${initial.id}`
 await page.goto(url);await page.locator('.director-topbar').waitFor()
 const close=page.getByRole('button',{name:'关闭面板',exact:true});if(await close.isVisible())await close.click()
 await page.getByRole('button',{name:'打开安巷指挥助手',exact:true}).click()
 await page.getByRole('button',{name:'目标计划',exact:true}).click()
 const tasks=page.getByRole('region',{name:'案例责任任务',exact:true})
 await tasks.locator('summary').click()
 await tasks.getByRole('button',{name:new RegExp(gas.title)}).click()
 const task=page.locator('#focused-task-'+gas.id),guidance=task.locator('.task-guidance')
 await guidance.getByText('现场读取于',{exact:false}).waitFor()
 assert.equal(await page.locator('.task-workflow').count(),1)
 assert.equal(await page.locator('.scene-assistant').isVisible(),false)
 assert.equal(await guidance.locator('details[data-knowledge-chunk]').count()>0,true)
 assert.ok((await guidance.innerText()).includes('时钟已暂停'))
 for(const [width,height]of [[1366,650],[768,1024],[390,844],[360,780]]){
   await page.setViewportSize({width,height});await guidance.locator('summary').first().scrollIntoViewIfNeeded()
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`overflow at ${width}`)
   const controls=await guidance.getByRole('button',{name:'更新任务依据',exact:true}).boundingBox();assert.ok(controls.height>=44)
   const top=await page.locator('.director-topbar').boundingBox();assert.ok(top.y>=0&&top.y+top.height<=height)
   await page.screenshot({path:`${out}/guidance-${width}.png`});records.push({width,height,noOverflow:true})
 }
 await page.setViewportSize({width:1366,height:650})
 await guidance.getByRole('button',{name:'定位任务对象',exact:true}).click()
 await page.getByLabel('透视楼层',{exact:true}).waitFor()
 assert.equal(await page.getByLabel('观察楼栋',{exact:true}).inputValue(),initial.simulation.environment.indoor.building_id)
 assert.equal(await page.getByLabel('透视楼层',{exact:true}).inputValue(),String(gas.target_floor))
 await page.getByText('燃气阀',{exact:true}).first().waitFor()
 await page.screenshot({path:out+'/device-1366.png'})
 await command('resume')
 await page.getByRole('button',{name:'打开处置任务',exact:true}).click()
 const gasTask=page.locator('.task-workflow').filter({has:page.getByRole('heading',{name:gas.title,exact:true})})
 await gasTask.getByRole('button',{name:'总控代办此任务',exact:true}).click()
 await gasTask.getByRole('button',{name:'回执已到达目标',exact:true}).click()
 const evidence=gasTask.locator('textarea');await evidence.fill('核验草稿：检查设备与现场情况，尚未提交。')
 const details=gasTask.locator('.task-guidance');if(!await details.evaluate(element=>element.open))await details.locator('summary').first().click()
 await details.getByText('现场读取于',{exact:false}).waitFor()
 const citation=details.locator('details[data-knowledge-chunk]').first();await citation.locator('summary').click()
 await citation.getByRole('button',{name:'定位这份资料的引用片段',exact:true}).click()
 await details.getByRole('region',{name:'任务引用原文',exact:true}).waitFor()
 assert.equal(await evidence.inputValue(),'核验草稿：检查设备与现场情况，尚未提交。')
 await page.setViewportSize({width:390,height:844});await details.getByRole('button',{name:'返回任务依据',exact:true}).scrollIntoViewIfNeeded()
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth))
 const notice=page.locator('.director-drawer>.ui-toast')
 if(await notice.isVisible()){
   const noticeBox=await notice.boundingBox(),returnBox=await details.getByRole('button',{name:'返回任务依据',exact:true}).boundingBox()
   assert.ok(noticeBox.y+noticeBox.height<=returnBox.y,'The receipt must not cover the reference return button')
 }
 await page.screenshot({path:out+'/citation-390.png'})
 await details.getByRole('button',{name:'返回任务依据',exact:true}).click()
 assert.equal(await evidence.inputValue(),'核验草稿：检查设备与现场情况，尚未提交。')
 await page.route('**/tasks/*/guidance',route=>route.abort('failed'))
 await details.getByRole('button',{name:'更新任务依据',exact:true}).click()
 await details.getByRole('alert').waitFor()
 assert.equal(await evidence.inputValue(),'核验草稿：检查设备与现场情况，尚未提交。')
 await page.unroute('**/tasks/*/guidance')
 await details.getByRole('button',{name:'更新任务依据',exact:true}).click()
 await details.getByRole('alert').waitFor({state:'hidden'})
 await command('pause')
 const final=await get();assert.equal(final.tasks.find(t=>t.id===gas.id).status,'verifying')
 assert.ok(!final.tasks.find(t=>t.id===gas.id).evidence)
 assert.deepEqual(errors,[])
 writeFileSync(out+'/result.json',JSON.stringify({drillId:initial.id,runId:run.id,taskId:gas.id,caseTasks:4,records,deviceFloor:gas.target_floor,deviceId:gas.target_device_id,draftPreserved:true,networkRetry:true,pageErrors:errors,finalStatus:final.status},null,2))
 console.log(JSON.stringify({ok:true,records:records.length,draftPreserved:true,networkRetry:true,deviceFloor:gas.target_floor}))
}catch(error){if(page)await page.screenshot({path:out+'/failure.png'}).catch(()=>{});throw error}finally{if(cleanup)await cleanup().catch(()=>{});await browser.close()}
