// Real isolated API/database: upload, review, publish, reload, retrieve and withdraw.
import assert from 'node:assert/strict'
import { mkdirSync, writeFileSync } from 'node:fs'
const { default: playwright } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await playwright.chromium.launch({ headless:true,
  ...(process.env.QA_BROWSER_PATH?{executablePath:process.env.QA_BROWSER_PATH}:{}) })
const base=process.env.QA_BASE_URL||'http://127.0.0.1:5181'
const api=process.env.QA_API_URL||'http://127.0.0.1:8011/api/v1'
const output='../output/playwright/knowledge';mkdirSync(output,{recursive:true})
try {
  const context=await browser.newContext(), page=await context.newPage(), errors=[]
  page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(20000)
  const login=await context.request.post(api+'/auth/login',{data:{username:'admin',password:process.env.QA_PASSWORD}})
  assert.ok(login.ok(),'QA login failed')
  const token=(await login.json()).access_token, headers={Authorization:'Bearer '+token}
  await page.setViewportSize({width:1440,height:900})
  await page.goto(base+'/projects?section=knowledge')
  await page.getByRole('heading',{name:'知识与预案',exact:true}).waitFor()
  await page.getByRole('button',{name:'添加资料',exact:true}).click()
  const title='厨房护送登记验收 '+Date.now()
  await page.getByLabel('资料名称',{exact:true}).fill(title)
  await page.locator('.knowledge-center__filters select').nth(1).selectOption('kitchen_fire')
  const content='槐荫厨房护送登记预案：三层独居老人由值守员实际会合后同行。到达集合点后逐人清点，确认身份，不能将到场直接当作完成清点。'
  await page.getByLabel('上传资料',{exact:true}).setInputFiles({name:'社区预案.txt',mimeType:'text/plain',buffer:Buffer.from(content)})
  const saved=page.waitForResponse(r=>r.url()===api+'/knowledge/documents'&&r.request().method()==='POST')
  await page.getByRole('button',{name:'保存草稿',exact:true}).click()
  const response=await saved;assert.equal(response.status(),201)
  const document=await response.json();assert.equal(document.versions[0].status,'draft')
  await page.reload()
  await page.getByRole('button').filter({hasText:title}).click()
  await page.getByRole('button',{name:'提交审核',exact:true}).click()
  await page.getByLabel('已核对正文、来源与适用范围').check()
  await page.getByRole('button',{name:'确认审核并发布',exact:true}).click()
  await page.getByRole('status').filter({hasText:'已发布，后续检索立即使用该版本。'}).waitFor()
  let evidence
  for(const [width,height] of [[1440,900],[390,844]]) {
    await page.setViewportSize({width,height})
    await page.getByRole('button',{name:'检索资料',exact:true}).click()
    await page.getByLabel('问题或关键词').fill('槐荫厨房护送登记预案')
    const searched=page.waitForResponse(r=>r.url()===api+'/knowledge/search')
    await page.getByRole('button',{name:'检索发布资料',exact:true}).click()
    const result=await (await searched).json()
    assert.ok(result.hits.some(h=>h.document_id===document.id))
    evidence=result
    await page.locator('.knowledge-evidence summary').filter({hasText:title}).click()
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth))
    await page.screenshot({path:`${output}/search-${width}.png`,fullPage:true})
  }
  await page.getByRole('button').filter({hasText:title}).click()
  await page.getByRole('button',{name:'停用当前版本',exact:true}).click()
  await page.getByRole('status').filter({hasText:'已停用，后续检索不再使用该版本。'}).waitFor()
  const after=await context.request.post(api+'/knowledge/search',{headers,data:{query:'槐荫厨房护送登记预案',scenario:'kitchen_fire'}})
  assert.ok(!(await after.json()).hits.some(h=>h.document_id===document.id))
  const pinned=await context.request.get(api+'/knowledge/retrievals/'+evidence.retrieval_id,{headers})
  assert.ok((await pinned.json()).hits.some(h=>h.document_id===document.id&&h.content===content))
  const demoResponse=await context.request.post(api+'/communities/demo-ready',{headers})
  assert.ok(demoResponse.ok(),'Isolated demo setup failed')
  const demo=await demoResponse.json(), root=api+'/drills/'+demo.drill_id
  const chatResponse=await context.request.post(root+'/assistant/chat',{headers,data:{message:'充电棚道路堵塞了，应怎样安排居民护送？',use_model:false}})
  assert.ok(chatResponse.ok(),'Real assistant knowledge retrieval failed')
  const chat=await chatResponse.json()
  assert.ok(chat.knowledge.hits.length&&chat.answer.includes('[K'))
  assert.ok(chat.knowledge.hits.every(h=>['all','charging_shed'].includes(h.scenario)))
  const prior=await (await context.request.get(root+'/agent/runs',{headers})).json()
  for(const run of prior.runs.filter(r=>r.goal.startsWith('知识验收')&&['awaiting_approval','needs_review'].includes(r.status))){
    await context.request.post(root+'/agent/runs/'+run.id+'/actions',{headers,data:{action:'stop',revision:run.revision}})
  }
  const planned=await context.request.post(root+'/agent/runs',{headers,data:{request_id:'knowledge-e2e-'+Date.now(),goal:'知识验收：将居民疏散并优先护送独居老人',priority_assist:true,use_model:false}})
  assert.equal(planned.status(),201,await planned.text())
  const plan=await planned.json()
  assert.ok(plan.knowledge.hits.length&&plan.knowledge.retrieval_id)
  assert.deepEqual(errors,[])
  const report={document_id:document.id,publication:'real database',upload:'TXT extraction in subprocess',
    states:['draft','review','published','withdrawn'],widths:[1440,390],pinnedEvidence:true,
    assistantKnowledgeHits:chat.knowledge.hits.length,planKnowledgeHits:plan.knowledge.hits.length,pageErrors:errors}
  writeFileSync(output+'/result.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report))
}finally{await browser.close()}
