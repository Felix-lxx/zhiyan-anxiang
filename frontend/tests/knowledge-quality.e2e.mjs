// Production UI + an explicitly isolated API; model and embedding consent stay off.
import assert from 'node:assert/strict'
import { mkdirSync, writeFileSync } from 'node:fs'
const { default: playwright } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await playwright.chromium.launch({headless:true,
  ...(process.env.QA_BROWSER_PATH?{executablePath:process.env.QA_BROWSER_PATH}:{})})
const base=process.env.QA_BASE_URL||'http://127.0.0.1:5181',api=process.env.QA_API_URL||'http://127.0.0.1:8011/api/v1'
const output='../output/playwright/rag-quality-20261104';mkdirSync(output,{recursive:true})
try{
  const context=await browser.newContext(),page=await context.newPage(),errors=[],records=[]
  page.setDefaultTimeout(20000);page.on('pageerror',error=>errors.push(error.message))
  const login=await context.request.post(api+'/auth/login',{data:{username:'admin',password:process.env.QA_PASSWORD}})
  assert.ok(login.ok());const headers={Authorization:'Bearer '+(await login.json()).access_token}
  const demoResponse=await context.request.post(api+'/communities/demo-ready',{headers})
  assert.ok(demoResponse.ok());const demo=await demoResponse.json()
  for(const [width,height] of [[1440,900],[390,844]]){
    await page.setViewportSize({width,height});await page.goto(base+'/projects?section=knowledge')
    await page.getByRole('button',{name:'检索资料',exact:true}).click()
    await page.getByLabel('问题或关键词',{exact:true}).fill('燃气泄漏能不能开抽油烟机？')
    const searched=page.waitForResponse(response=>response.url()===api+'/knowledge/search')
    await page.getByRole('button',{name:'检索发布资料',exact:true}).click()
    const result=await(await searched).json()
    assert.ok(result.hits.some(hit=>hit.document_id==='builtin-household-gas-response-01'))
    await page.locator('.knowledge-evidence summary').first().click()
    await page.locator('.knowledge-evidence .knowledge-match').first().waitFor()
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth))
    await page.screenshot({path:`${output}/source-match-${width}.png`,fullPage:true})
    await page.getByLabel('问题或关键词',{exact:true}).fill('小区附近有什么餐厅推荐？')
    const empty=page.waitForResponse(response=>response.url()===api+'/knowledge/search')
    await page.getByRole('button',{name:'检索发布资料',exact:true}).click()
    assert.deepEqual((await(await empty).json()).hits,[])
    await page.getByText('没有命中适用资料，请补充关键词或社区预案。',{exact:true}).waitFor()
    await page.screenshot({path:`${output}/no-match-${width}.png`,fullPage:true})
    await page.goto(`${base}/communities/${demo.community.id}/operations?scene=${demo.scene_id}&drill=${demo.drill_id}`)
    let automaticallySent=0
    const detectSend=request=>{if(request.url().endsWith('/assistant/chat'))automaticallySent++}
    page.on('request',detectSend)
    await page.getByRole('button',{name:'询问当前任务与依据',exact:true}).click()
    await page.locator('#scene-assistant-question').waitFor()
    assert.ok((await page.locator('#scene-assistant-question').inputValue()).includes('应先处理什么'))
    assert.equal(automaticallySent,0,'Opening the assistant only prepares an editable question')
    page.off('request',detectSend)
    for(const checkbox of await page.locator('.scene-assistant__connection input[type=checkbox]').all())await checkbox.uncheck()
    await page.locator('#scene-assistant-question').fill('充电棚通道堵了怎么改道？')
    const answered=page.waitForResponse(response=>response.url().endsWith('/assistant/chat')&&response.request().method()==='POST')
    await page.locator('.scene-assistant__compose button[type=submit]').click()
    const answerResponse=await answered
    assert.equal(answerResponse.request().postDataJSON().use_model,false)
    assert.equal(answerResponse.request().postDataJSON().semantic_retrieval,false)
    const answer=await answerResponse.json()
    assert.ok(answer.sources.some(source=>source.id==='K1'&&source.match?.ranking_revision==='lexical-v2'))
    await page.getByRole('button',{name:'查看依据 K1',exact:true}).first().click()
    await page.locator('.scene-assistant__sources [data-source="K1"] .knowledge-match').waitFor()
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth))
    await page.screenshot({path:`${output}/assistant-match-${width}.png`})
    const source=answer.sources.find(source=>source.id==='K1')
    await page.locator('.scene-assistant__sources [data-source="K1"]').getByRole('button',{name:'定位引用片段',exact:true}).click()
    await page.locator('.knowledge-reader article[data-cited="true"]').waitFor()
    assert.equal(new URL(page.url()).searchParams.get('chunk'),source.chunk_id)
    assert.equal(await page.getByLabel('资料版本',{exact:true}).inputValue(),source.version_id)
    records.push({width,knowledgeVersion:result.hits[0].version,match:result.hits[0].match,assistantMode:answer.mode})
  }
  assert.deepEqual(errors,[])
  writeFileSync(output+'/result.json',JSON.stringify({records,pageErrors:errors},null,2));console.log(JSON.stringify({widths:records.map(item=>item.width),modelCalls:false,pageErrors:errors}))
}finally{await browser.close()}
