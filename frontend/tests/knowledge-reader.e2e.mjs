// Real isolated database: long-document retrieval, exact citations and immutable versions.
import assert from 'node:assert/strict'
import { mkdirSync, writeFileSync } from 'node:fs'
const { default: playwright } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await playwright.chromium.launch({headless:true,
  ...(process.env.QA_BROWSER_PATH?{executablePath:process.env.QA_BROWSER_PATH}:{})})
const base=process.env.QA_BASE_URL||'http://127.0.0.1:5181',api=process.env.QA_API_URL||'http://127.0.0.1:8011/api/v1'
const output='../output/playwright/knowledge-reader-20261104';mkdirSync(output,{recursive:true})
try{
  const context=await browser.newContext(),page=await context.newPage(),errors=[]
  page.setDefaultTimeout(18000);page.on('pageerror',error=>errors.push(error.message))
  const login=await context.request.post(api+'/auth/login',{data:{username:'admin',password:process.env.QA_PASSWORD}})
  assert.ok(login.ok());const headers={Authorization:'Bearer '+(await login.json()).access_token}
  const tag='QX'+Date.now(),query=tag+' 燃气隔离核验'
  const target=`${tag} 燃气隔离核验：指定值守员必须核对设备身份并到位后提交实际处置证据，不能把移动到设备旁当作已关闭。`
  const content=Array.from({length:14},(_,index)=>(`第${index+1}部分：日常设施检查应核对记录和责任岗位。`).repeat(26)).join('\n\n')+'\n\n'+target
  const payload={title:tag+' 厨房组织预案',content,scenario:'kitchen_fire'}
  const created=await context.request.post(api+'/knowledge/documents',{headers,data:payload});assert.equal(created.status(),201)
  const doc=await created.json(),version=doc.versions[0]
  async function publish(document){
    const root=api+'/knowledge/documents/'+document.id+'/actions',version_id=document.versions[0].id
    assert.ok((await context.request.post(root,{headers,data:{action:'review',version_id}})).ok())
    assert.ok((await context.request.post(root,{headers,data:{action:'publish',version_id}})).ok())
  }
  await publish(doc)
  let hit,searches=0
  page.on('request',request=>{if(request.url()===api+'/knowledge/search')searches++})
  for(const [width,height]of [[1440,900],[390,844]]){
    await page.setViewportSize({width,height});await page.goto(base+'/projects?section=knowledge')
    await page.getByRole('button',{name:'检索资料',exact:true}).click()
    await page.getByLabel('问题或关键词',{exact:true}).fill(query)
    const response=page.waitForResponse(response=>response.url()===api+'/knowledge/search')
    await page.getByRole('button',{name:'检索发布资料',exact:true}).click()
    const result=await(await response).json();hit=result.hits.find(item=>item.document_id===doc.id)
    assert.ok(hit&&hit.content.includes(target));assert.notEqual(hit.chunk_id,version.chunks[0].id)
    const details=page.locator(`[data-knowledge-chunk="${hit.chunk_id}"]`)
    await details.locator('summary').click()
    await details.getByRole('button',{name:'定位这份资料的引用片段',exact:true}).click()
    const reader=page.getByRole('region',{name:'版本正文',exact:true})
    await page.locator('.knowledge-reader article[data-cited="true"]').waitFor()
    assert.equal(await page.getByLabel('阅读位置',{exact:true}).inputValue(),hit.chunk_id)
    assert.ok((await reader.innerText()).includes(target))
    assert.equal(await reader.locator('article').count(),1,'Default reading renders only the selected segment')
    await page.waitForURL(url=>url.searchParams.get('chunk')===hit.chunk_id)
    await page.getByRole('button',{name:'上一段',exact:true}).click()
    assert.notEqual(await page.getByLabel('阅读位置',{exact:true}).inputValue(),hit.chunk_id)
    await page.getByRole('button',{name:'下一段',exact:true}).click()
    assert.equal(await page.getByLabel('阅读位置',{exact:true}).inputValue(),hit.chunk_id)
    const continuous=page.getByRole('checkbox',{name:/连续阅读全部/})
    await continuous.check();assert.equal(await reader.locator('article').count(),version.chunks.length)
    await continuous.uncheck()
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth))
    await page.screenshot({path:`${output}/cited-section-${width}.png`,fullPage:true})
    const before=searches
    await page.getByRole('button',{name:/返回检索结果/}).click()
    await page.getByLabel('问题或关键词',{exact:true}).waitFor()
    assert.equal(await page.getByLabel('问题或关键词',{exact:true}).inputValue(),query)
    assert.equal(searches,before,'Returning must preserve the original retrieval, not issue a fresh search')
    assert.ok(await page.locator(`[data-knowledge-chunk="${hit.chunk_id}"]`).evaluate(element=>element.open))
    await page.screenshot({path:`${output}/returned-search-${width}.png`,fullPage:true})
  }
  const revised=await context.request.post(api+'/knowledge/documents/'+doc.id+'/versions',{headers,data:{...payload,content:content+'\n\n新版增加交接核对。'}})
  assert.ok(revised.ok());const next=await revised.json();await publish(next)
  const url=`${base}/projects?section=knowledge&document=${doc.id}&version=${version.id}&chunk=${hit.chunk_id}`
  await page.goto(url);await page.locator('.knowledge-reader article[data-cited="true"]').waitFor()
  assert.equal(await page.getByLabel('资料版本',{exact:true}).inputValue(),version.id)
  assert.ok((await page.locator('.knowledge-reader article').innerText()).includes(target))
  await page.reload();await page.locator('.knowledge-reader article[data-cited="true"]').waitFor()
  assert.equal(await page.getByLabel('阅读位置',{exact:true}).inputValue(),hit.chunk_id)
  await page.getByLabel('资料版本',{exact:true}).selectOption(next.versions[0].id)
  await page.waitForURL(value=>value.searchParams.get('version')===next.versions[0].id&&!value.searchParams.has('chunk'))
  assert.equal(await page.locator('.knowledge-reader article[data-cited="true"]').count(),0)
  await page.goto(url.replace(hit.chunk_id,next.versions[0].chunks[0].id))
  await page.getByRole('alert').filter({hasText:'引用片段不属于此资料版本'}).waitFor()
  assert.equal(await page.locator('.knowledge-reader').count(),0)
  assert.deepEqual(errors,[])
  writeFileSync(output+'/result.json',JSON.stringify({document:doc.id,version:version.id,chunks:version.chunks.length,chunk:hit.chunk_id,
    widths:[1440,390],returnPreservesSearch:true,oldVersionReload:true,wrongVersionChunkRejected:true,pageErrors:errors},null,2))
  console.log(JSON.stringify({chunks:version.chunks.length,widths:[1440,390],oldVersionReload:true,wrongVersionChunkRejected:true,pageErrors:errors}))
  assert.ok((await context.request.post(api+'/knowledge/documents/'+doc.id+'/actions',{headers,data:{action:'withdraw',version_id:next.versions[0].id}})).ok())
}finally{await browser.close()}
