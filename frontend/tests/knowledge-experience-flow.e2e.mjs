// Real isolated simulation, scheduler, knowledge lifecycle and production UI.
import assert from 'node:assert/strict'
import {mkdirSync,writeFileSync} from 'node:fs'
const {default:p}=await import(process.env.PLAYWRIGHT_MODULE||'playwright')
const base=process.env.QA_BASE_URL||'http://127.0.0.1:5181',api=process.env.QA_API_URL||'http://127.0.0.1:8011/api/v1'
const output='../output/playwright/knowledge-experience';mkdirSync(output,{recursive:true})
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
 const drill=await request('/scenes/'+demo.scene_id+'/drills',{name:'复盘经验闭环验收',time_scale:4,training_mode:'teaching'})
 const root='/drills/'+drill.id
 let state=await request(root+'/state',{action:'start'},'PATCH')
 const ids=state.simulation.residents.filter(p=>!p.vulnerable).slice(0,2).map(p=>p.id)
 const plan=await request(root+'/agent/runs',{request_id:'experience-ui-'+Date.now(),goal:'分流疏散居民，复盘同批人员的出口安排',
  resident_ids:ids,priority_assist:false,pause_for_review:true})
 await page.setViewportSize({width:1440,height:900})
 await page.goto(`${base}/communities/${demo.community.id}/operations?scene=${demo.scene_id}&drill=${drill.id}`)
 await page.locator('canvas').first().waitFor()
 await page.locator('[data-director-action="assistant"]').click()
 const assistant=page.getByLabel('场景 AI 助手',{exact:true})
 await assistant.getByRole('button',{name:'目标计划',exact:true}).click()
 await assistant.getByRole('button',{name:'确认方案并执行',exact:true}).click()
 let observed
 for(let attempt=0;attempt<65;attempt++){
  const run=(await request(root+'/agent/runs')).runs.find(run=>run.id===plan.id)
  observed=run.outcomes.find(outcome=>outcome.result?.comparable)
  if(observed)break
  await page.waitForTimeout(700)
 }
 assert.ok(observed,'Background scheduler did not complete a comparable observation')
 await request(root+'/state',{action:'pause'},'PATCH')
 await assistant.getByRole('button',{name:'依据',exact:true}).click()
 const saved=page.waitForResponse(response=>response.url()===api+'/knowledge/experiences')
 await assistant.getByRole('button',{name:'保存为经验草稿',exact:true}).click()
 const createdResponse=await saved;assert.ok(createdResponse.ok(),await createdResponse.text())
 const created=await createdResponse.json(),document=created.document,source=document.experience
 assert.equal(document.versions[0].status,'draft')
 assert.deepEqual(source.actual,observed.result.actual)
 await page.getByRole('button',{name:'打开经验资料与审核',exact:true}).click()
 await page.getByRole('heading',{name:document.title,exact:true}).waitFor()
 const widths=[]
 for(const [width,height]of [[1440,900],[390,844]]){
  await page.setViewportSize({width,height})
  await page.getByLabel('经验原始观察依据',{exact:true}).scrollIntoViewIfNeeded()
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth))
  await page.screenshot({path:`${output}/source-${width}.png`,fullPage:true});widths.push(width)
 }
 await page.getByRole('button',{name:'修订为新草稿',exact:true}).click()
 await page.getByRole('button',{name:'语音输入',exact:true}).waitFor()
 const marker='复训对照N4-'+Date.now()
 const content=await page.getByLabel('资料正文',{exact:true}).inputValue()
 await page.getByLabel('资料正文',{exact:true}).fill(content+'\n复盘补充：'+marker+'；下一次保持场景参数不变，对照出口分流和通知时序。')
 const revision=page.waitForResponse(response=>response.url()===api+'/knowledge/documents/'+document.id+'/versions')
 await page.getByRole('button',{name:'保存草稿',exact:true}).click()
 const revised=await(await revision).json()
 assert.equal(revised.versions[0].number,2)
 assert.equal(revised.experience.basis_hash,source.basis_hash)
 const query={query:marker,community_id:document.community_id,scenario:document.scenario}
 assert.ok(!(await request('/knowledge/search',query)).hits.some(hit=>hit.document_id===document.id))
 await page.getByRole('button',{name:'提交审核',exact:true}).click()
 await page.getByLabel('已核对观察事实、适用条件与正文结论',{exact:true}).check()
 await page.getByRole('button',{name:'确认审核并发布',exact:true}).click()
 await page.getByRole('status').filter({hasText:'已发布，后续检索立即使用该版本。'}).waitFor()
 const result=await request('/knowledge/search',query)
 const hit=result.hits.find(hit=>hit.document_id===document.id)
 assert.ok(hit&&hit.version===2&&hit.experience.basis_hash===source.basis_hash)
 await page.goto(`${base}/projects?section=knowledge&document=${document.id}&version=${hit.version_id}`)
 await page.getByRole('heading',{name:document.title,exact:true}).waitFor()
 const replayResponse=page.waitForResponse(response=>response.url().includes('/replay?at_seconds='+source.observed_at))
 await page.getByRole('button',{name:'打开来源场次的观察时刻',exact:true}).click()
 const replay=await(await replayResponse).json();assert.equal(replay.at_seconds,source.observed_at)
 const next=await request('/scenes/'+demo.scene_id+'/drills',{name:'复盘经验下一轮检索验收',time_scale:1})
 const nextPlan=await request('/drills/'+next.id+'/agent/runs',{request_id:'experience-next-'+Date.now(),
  goal:'组织居民分流疏散，并核对'+marker,resident_ids:ids,priority_assist:false})
 assert.ok(nextPlan.knowledge.hits.some(hit=>hit.document_id===document.id&&hit.experience.basis_hash===source.basis_hash))
 assert.deepEqual(errors,[])
 const report={drill_id:drill.id,plan_id:plan.id,document_id:document.id,observation:source.observed_at,
  matchedResidents:source.population,publishedVersion:2,basisHashPreserved:true,sourceReplay:true,nextPlanRetrieved:true,
  widths,pageErrors:errors,modelCalls:'none: isolated offline backend'}
 writeFileSync(output+'/report.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report))
}finally{await browser.close()}
