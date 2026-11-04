// Real isolated API/database; uses no embedding provider and alters no runtime data.
import assert from 'node:assert/strict'
import { mkdirSync, writeFileSync } from 'node:fs'
const { default: playwright } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await playwright.chromium.launch({headless:true,
  ...(process.env.QA_BROWSER_PATH?{executablePath:process.env.QA_BROWSER_PATH}:{})})
const base=process.env.QA_BASE_URL||'http://127.0.0.1:5181',api=process.env.QA_API_URL||'http://127.0.0.1:8011/api/v1'
const output='../output/playwright/rag-repair-20261104';mkdirSync(output,{recursive:true})
try {
  const context=await browser.newContext(),page=await context.newPage(),errors=[],checks={}
  page.on('pageerror',error=>errors.push(error.message));page.setDefaultTimeout(15000)
  page.on('requestfailed',request=>console.log('Failed request: '+request.url()+' '+request.failure()?.errorText))
  const login=await context.request.post(api+'/auth/login',{data:{username:'admin',password:process.env.QA_PASSWORD}})
  assert.ok(login.ok());const headers={Authorization:'Bearer '+(await login.json()).access_token}
  async function get(path){const r=await context.request.get(api+path,{headers});assert.ok(r.ok(),path);return r.json()}
  const catalog=await get('/knowledge/documents'),doc=catalog.items.find(item=>item.id==='builtin-household-gas-response-01')
  assert.ok(doc);checks.builtinDocuments=catalog.items.filter(item=>item.builtin).length
  const search=await context.request.post(api+'/knowledge/search',{headers,data:{query:'燃气泄漏 电器',scenario:'kitchen_fire'}})
  const hits=(await search.json()).hits;assert.ok(hits.some(item=>item.document_id===doc.id));checks.gasRetrieval=true
  await page.setViewportSize({width:1440,height:900})
  await page.goto(`${base}/projects?section=knowledge&document=${doc.id}&version=${doc.versions[0].id}`)
  try { await page.getByRole('heading',{name:doc.title,exact:true}).waitFor() }
  catch(error){console.log(JSON.stringify({url:page.url(),text:(await page.locator('body').innerText()).slice(0,2200),errors}));throw error}
  await page.screenshot({path:output+'/source-1440.png',fullPage:true})
  await page.evaluate(id=>{history.pushState({...history.state},'',`/projects?section=knowledge&document=${id}&version=missing-rag-version`);dispatchEvent(new PopStateEvent('popstate',{state:history.state}))},doc.id)
  await page.getByRole('alert').filter({hasText:'引用的资料版本已不可访问'}).waitFor()
  assert.equal(await page.getByLabel('资料版本',{exact:true}).count(),0,'Never display another version as the requested source')
  checks.invalidPinnedVersion=true
  const demoResponse=await context.request.post(api+'/communities/demo-ready',{headers})
  assert.ok(demoResponse.ok());const community=(await demoResponse.json()).community.id
  for(const [width,height] of [[390,844],[1440,900]]){
    await page.setViewportSize({width,height});await page.goto(`${base}/communities/${community}/map`)
    await page.locator('.map-marker').first().waitFor()
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth))
    if(width===390){
      await page.waitForFunction(()=>[...document.querySelectorAll('.map-marker')].some(el=>el.getAttribute('data-short').endsWith('处')))
      const overlaps=await page.locator('.map-marker').evaluateAll(elements=>{
        let count=0
        for(let i=0;i<elements.length;i++)for(let j=i+1;j<elements.length;j++){
          const a=elements[i].getBoundingClientRect(),b=elements[j].getBoundingClientRect()
          if(Math.min(a.right,b.right)-Math.max(a.left,b.left)>1&&Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>1)count++
        }return count
      })
      assert.equal(overlaps,0);checks.mobileMarkerOverlaps=overlaps
      const group=page.locator('.map-marker[data-short$="处"]').first();await group.click()
      const picker=page.locator('.map-nearby-picker select');await picker.waitFor()
      const ids=await picker.locator('option').evaluateAll(options=>options.map(option=>option.value))
      assert.ok(ids.length>1);await picker.selectOption(ids[1])
      await page.screenshot({path:output+'/map-selection-390.png',fullPage:true})
      const selected=page.locator('.map-marker[data-selected="true"]')
      const before=await selected.evaluate(el=>({x:parseFloat(el.style.left),y:parseFloat(el.style.top)}))
      const response=page.waitForResponse(r=>r.url().includes('/map-objects/'+ids[1])&&r.request().method()==='PATCH')
      await selected.press('ArrowRight');const saved=await response;assert.ok(saved.ok())
      await page.reload();await page.locator('.map-marker').first().waitFor()
      const objects=await get('/communities/'+community+'/map-objects')
      const list=Array.isArray(objects)?objects:objects.items
      assert.equal(list.find(item=>item.id===ids[1]).geometry.x,Math.min(98,before.x+2))
      // Restore the isolated fixture to its original geometry.
      assert.ok((await context.request.patch(api+'/communities/'+community+'/map-objects/'+ids[1],{headers,data:{geometry:before}})).ok())
      checks.clusterSelectionSaved=true
      checks.coordinateFont=await page.locator('.map-coordinate-readout').evaluate(el=>parseFloat(getComputedStyle(el).fontSize))
      assert.ok(checks.coordinateFont>=14)
    }
    await page.screenshot({path:`${output}/map-${width}.png`,fullPage:true})
  }
  assert.deepEqual(errors,[]);checks.pageErrors=errors
  writeFileSync(output+'/result.json',JSON.stringify(checks,null,2));console.log(JSON.stringify(checks))
}finally{await browser.close()}
