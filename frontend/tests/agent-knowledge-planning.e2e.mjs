// Real isolated API/database + production director components. No external model calls.
import assert from 'node:assert/strict'
import { mkdirSync, writeFileSync } from 'node:fs'
const {default:p}=await import(process.env.PLAYWRIGHT_MODULE||'playwright')
const base=process.env.QA_BASE_URL||'http://127.0.0.1:5181'
const api=process.env.QA_API_URL||'http://127.0.0.1:8011/api/v1'
const output='../output/playwright/agent-knowledge';mkdirSync(output,{recursive:true})
const browser=await p.chromium.launch({headless:true,...(process.env.QA_BROWSER_PATH?{executablePath:process.env.QA_BROWSER_PATH}:{})})
try{
  const context=await browser.newContext(),page=await context.newPage(),errors=[]
  page.setDefaultTimeout(30000);page.on('pageerror',e=>errors.push(e.message))
  const auth=await context.request.post(api+'/auth/login',{data:{username:'admin',password:process.env.QA_PASSWORD}})
  assert.ok(auth.ok(),'QA login failed')
  const token=(await auth.json()).access_token,headers={Authorization:'Bearer '+token}
  const request=async(path,body,method=body===undefined?'GET':'POST')=>{
    const response=await context.request.fetch(api+path,{method,headers,data:body})
    assert.ok(response.ok(),`${path}: ${response.status()} ${await response.text()}`)
    return response.json()
  }
  const demo=await request('/communities/demo-ready',{})
  const drill=await request('/scenes/'+demo.scene_id+'/drills',{name:'目标约束与知识联动验收',time_scale:1,training_mode:'teaching'})
  const root='/drills/'+drill.id
  await request(root+'/state',{action:'start'},'PATCH');await request(root+'/state',{action:'pause'},'PATCH')
  const state=await request(root)
  const person=state.simulation.residents.find(p=>!p.vulnerable),floor=person.floor
  const references=await request('/knowledge/search',{query:'目标约束 禁用出口 工具预演',scenario:'all'})
  assert.ok(references.hits.some(hit=>hit.document_id==='builtin-platform-planning-01'))
  await page.setViewportSize({width:1440,height:900})
  await page.goto(`${base}/communities/${demo.community.id}/operations?scene=${demo.scene_id}&drill=${drill.id}`)
  await page.locator('canvas').first().waitFor()
  await page.locator('[data-director-action="assistant"]').click()
  const assistant=page.getByLabel('场景 AI 助手',{exact:true})
  await assistant.getByRole('button',{name:'目标计划',exact:true}).click()
  await assistant.getByLabel('演练目标',{exact:true}).fill('分流疏散本楼目标居民，降低暴露，并核对目标约束')
  await assistant.getByLabel('目标范围',{exact:true}).selectOption(person.building_id)
  await assistant.getByText('目标约束与优化取向',{exact:true}).click()
  await assistant.getByLabel('居住楼层（可选）',{exact:true}).fill(String(floor))
  await assistant.getByLabel('方案优化取向',{exact:true}).selectOption('low_exposure')
  await assistant.getByLabel('重点人员安排护送',{exact:true}).uncheck()
  const created=page.waitForResponse(r=>r.url()===api+root+'/agent/runs'&&r.request().method()==='POST')
  await assistant.getByRole('button',{name:'生成并比较方案',exact:true}).click()
  const response=await created;assert.equal(response.status(),201,await response.text())
  const plan=await response.json()
  assert.deepEqual(plan.scope.floors,[floor]);assert.equal(plan.planning.objective,'low_exposure')
  assert.ok(plan.knowledge.hits.length);assert.ok(plan.candidates.some(c=>c.can_apply))
  const reports=[]
  for(const [width,height]of [[1440,900],[390,844]]){
    await page.setViewportSize({width,height})
    await assistant.getByLabel('知识与工具规划记录',{exact:true}).scrollIntoViewIfNeeded()
    const trace=assistant.getByText('查看工具记录 · 事件 '+plan.planning.event_sequence,{exact:true})
    if(!(await trace.locator('..').getAttribute('open')) && !(await trace.evaluate(el=>el.parentElement.open)))await trace.click()
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth))
    assert.ok(await assistant.evaluate(el=>el.scrollWidth<=el.clientWidth+1))
    await page.screenshot({path:`${output}/planning-${width}.png`})
    reports.push({width,overflow:false,toolRecords:plan.planning.trace.length})
  }
  await assistant.getByRole('button',{name:'确认方案并执行',exact:true}).click()
  await assistant.getByRole('button',{name:'调整剩余行动',exact:true}).waitFor()
  const persisted=await request(root+'/agent/runs')
  const running=persisted.runs.find(r=>r.id===plan.id)
  assert.ok(running.steps.some(step=>step.command_id))
  assert.deepEqual(running.scope.floors,[floor])
  await request(root+'/state',{action:'pause'},'PATCH')
  assert.deepEqual(errors,[])
  const report={drill_id:drill.id,plan_id:plan.id,knowledgeHits:plan.knowledge.hits.length,
    selectedResidents:plan.summary.total,floor,reports,commands:running.steps.filter(s=>s.command_id).length,pageErrors:errors,
    modelCalls:'none: isolated backend configured offline',publication:'real seeded database'}
  writeFileSync(output+'/report.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report))
}finally{await browser.close()}
