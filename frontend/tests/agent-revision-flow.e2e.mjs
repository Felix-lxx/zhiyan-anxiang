// Real isolated database and production UI; no external LLM or speech requests.
import assert from 'node:assert/strict'
import {mkdirSync,writeFileSync} from 'node:fs'
const {default:p}=await import(process.env.PLAYWRIGHT_MODULE||'playwright')
const base=process.env.QA_BASE_URL||'http://127.0.0.1:5181',api=process.env.QA_API_URL||'http://127.0.0.1:8011/api/v1'
const output='../output/playwright/agent-revision';mkdirSync(output,{recursive:true})
const browser=await p.chromium.launch({headless:true,...(process.env.QA_BROWSER_PATH?{executablePath:process.env.QA_BROWSER_PATH}:{})})
try{
 const context=await browser.newContext(),page=await context.newPage(),errors=[]
 page.setDefaultTimeout(30000);page.on('pageerror',error=>errors.push(error.message))
 const auth=await context.request.post(api+'/auth/login',{data:{username:'admin',password:process.env.QA_PASSWORD}})
 assert.ok(auth.ok(),'QA login failed')
 const headers={Authorization:'Bearer '+(await auth.json()).access_token}
 async function request(path,body,method=body===undefined?'GET':'POST'){
  const response=await context.request.fetch(api+path,{method,headers,data:body})
  assert.ok(response.ok(),`${path} ${response.status()} ${await response.text()}`);return response.json()
 }
 const demo=await request('/communities/demo-ready',{})
 const drill=await request('/scenes/'+demo.scene_id+'/drills',{name:'异常影响与接续执行验收',time_scale:1,training_mode:'teaching'})
 const root='/drills/'+drill.id
 let data=await request(root+'/state',{action:'start'},'PATCH')
 for(const edge of data.simulation.road_network.edges.filter(edge=>edge.status!=='open'&&!edge.geometry_blocked))
  await request(root+'/roads/'+edge.id+'/reopen',{})
 data=await request(root+'/state',{action:'pause'},'PATCH')
 const person=data.simulation.residents.find(person=>!person.vulnerable)
 const ids=data.simulation.residents.filter(p=>p.building_id===person.building_id&&!p.vulnerable).slice(0,2).map(p=>p.id)
 const plan=await request(root+'/agent/runs',{request_id:'revision-ui-'+Date.now(),goal:'组织目标居民经北门分流疏散',
  resident_ids:ids,priority_assist:false,pause_for_review:true,forbidden_exits:['south']})
 assert.ok(plan.candidates.some(c=>c.can_apply),'Initial north-only proposal is not executable')
 await page.setViewportSize({width:1440,height:900})
 await page.goto(`${base}/communities/${demo.community.id}/operations?scene=${demo.scene_id}&drill=${drill.id}`)
 await page.locator('canvas').first().waitFor()
 await page.locator('[data-director-action="assistant"]').click()
 const assistant=page.getByLabel('场景 AI 助手',{exact:true})
 await assistant.getByRole('button',{name:'目标计划',exact:true}).click()
 await assistant.getByRole('button',{name:'确认方案并执行',exact:true}).click()
 await assistant.getByRole('button',{name:'调整剩余行动',exact:true}).waitFor()
 data=await request(root+'/state',{action:'pause'},'PATCH')
 let current=(await request(root+'/agent/runs')).runs.find(r=>r.id===plan.id)
 const originalCommands=current.steps.map(step=>step.command_id)
 const routeIds=new Set(current.steps.flatMap(step=>step.route_edge_ids||[]))
 // Private payloads do not expose internal step routes; the persisted candidate
 // is the same domain forecast approved by the UI above.
 for(const assignment of plan.candidates.find(c=>c.id===current.selected_candidate).assignments)
  for(const id of assignment.route_edge_ids)routeIds.add(id)
 const edge=data.simulation.road_network.edges.find(edge=>routeIds.has(edge.id)&&edge.name.includes('北')&&edge.status==='open')
 assert.ok(edge,'No north-side road belongs to this real proposal')
 await request(root+'/state',{action:'resume'},'PATCH')
 await request(root+'/commands',{command_id:'revision-block-'+Date.now(),kind:'event.inject',arguments:{event_type:'channel_blocked',road_edge_id:edge.id}})
 await request(root+'/state',{action:'pause'},'PATCH')
 current=(await request(root+'/agent/runs')).runs.find(r=>r.id===plan.id)
 assert.ok(current.impact.affected_count>0)
 if(current.status!=='needs_review')await assistant.getByRole('button',{name:'调整剩余行动',exact:true}).click()
 await assistant.getByRole('button',{name:'方案',exact:true}).click()
 await assistant.getByText('修订取向与禁用出口',{exact:true}).click()
 await assistant.getByLabel('禁止南侧出口',{exact:true}).uncheck()
 await assistant.getByLabel('禁止北侧出口',{exact:true}).check()
 await assistant.getByLabel('修订优化取向',{exact:true}).selectOption('low_exposure')
 const revisedResponse=page.waitForResponse(r=>r.url()===api+root+'/agent/runs/'+plan.id+'/actions'&&r.request().postDataJSON()?.action==='replan')
 await assistant.getByRole('button',{name:'按当前现场重新比较',exact:true}).click()
 const response=await revisedResponse;assert.ok(response.ok(),await response.text())
 const revised=await response.json()
 assert.ok(revised.revision_context.impact.affected_count>0)
 assert.equal(revised.revision_context.from_revision,1)
 assert.notEqual(revised.knowledge.retrieval_id,plan.knowledge.retrieval_id)
 assert.ok(revised.candidates.some(c=>c.can_apply))
 assert.ok(revised.candidates.every(c=>c.assignments.every(p=>p.exit==='south')))
 const widths=[]
 for(const [width,height]of [[1440,900],[390,844]]){
  await page.setViewportSize({width,height})
  await assistant.getByLabel('异常影响与修订差异',{exact:true}).scrollIntoViewIfNeeded()
  assert.ok(await assistant.evaluate(el=>el.scrollWidth<=el.clientWidth+1))
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth))
  await page.screenshot({path:`${output}/revision-${width}.png`});widths.push(width)
 }
 await assistant.getByRole('button',{name:'确认方案并执行',exact:true}).click()
 await assistant.getByRole('button',{name:'朗读当前执行摘要',exact:true}).waitFor()
 data=await request(root+'/state',{action:'pause'},'PATCH')
 const resumed=(await request(root+'/agent/runs')).runs.find(r=>r.id===plan.id)
 assert.equal(resumed.approved_revision,revised.revision)
 const commandIds=new Set(data.commands.map(command=>command.id))
 assert.ok(originalCommands.every(id=>commandIds.has(id)),'Revisions must retain original command evidence')
 assert.deepEqual(errors,[])
 const report={drill_id:drill.id,plan_id:plan.id,blockedRoad:edge.name,affectedResidents:revised.revision_context.impact.affected_count,
  newRevision:resumed.approved_revision,newKnowledge:revised.knowledge.hits.length,
  changedResidents:revised.revision_context.candidates.map(c=>c.changed_count),widths,originalCommandsRetained:true,pageErrors:errors}
 writeFileSync(output+'/report.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report))
}finally{await browser.close()}
