// Explicitly isolated API: validate actual director commands and core presentation.
import assert from 'node:assert/strict'
import {mkdirSync,writeFileSync} from 'node:fs'
const {default:playwright}=await import(process.env.PLAYWRIGHT_MODULE||'playwright')
const browser=await playwright.chromium.launch({headless:true,...(process.env.QA_BROWSER_PATH?{executablePath:process.env.QA_BROWSER_PATH}:{})})
const api=process.env.QA_API_URL||'http://127.0.0.1:8011/api/v1',base=process.env.QA_BASE_URL||'http://127.0.0.1:5181'
const out='../output/playwright/core-workspace-20261104';mkdirSync(out,{recursive:true})
try{
 const context=await browser.newContext(),page=await context.newPage(),errors=[],records=[]
 page.setDefaultTimeout(20000);page.on('pageerror',error=>errors.push(error.message))
 const login=await context.request.post(api+'/auth/login',{data:{username:'admin',password:process.env.QA_PASSWORD}})
 assert.ok(login.ok());const headers={Authorization:'Bearer '+(await login.json()).access_token}
 const demo=await(await context.request.post(api+'/communities/demo-ready',{headers})).json()
 const created=await context.request.post(`${api}/scenes/${demo.scene_id}/drills`,{headers,data:{name:'UI 自动验收 · 核心工作区',training_mode:'teaching',time_scale:1}})
 assert.equal(created.status(),201);const drill=await created.json(),root=api+'/drills/'+drill.id
 const url=`${base}/communities/${demo.community.id}/operations?scene=${demo.scene_id}&drill=${drill.id}`
 async function body(path){const r=await context.request.get(path,{headers});assert.ok(r.ok());return r.json()}
 async function closePanel(){const close=page.getByRole('button',{name:'关闭面板',exact:true});if(await close.isVisible())await close.click()}
 async function noOverflow(name,width){assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),name);records.push({name,width})}
 for(const [width,height]of [[1440,900],[1366,650],[390,844]]){
  await page.setViewportSize({width,height});await page.goto(url)
  await page.locator('.director-topbar').waitFor();await closePanel()
  const progress=page.getByRole('region',{name:'当前训练进展',exact:true});await progress.waitFor()
  assert.ok((await progress.innerText()).includes('到场 0/'))
  const badge=page.locator('[data-director-action="missions"] b');assert.ok(await badge.isVisible())
  assert.equal(await badge.innerText(),String(drill.tasks.length))
  assert.ok((await page.getByRole('button',{name:'打开复盘评分',exact:true}).innerText()).includes('评分依据'))
  const bounds=await progress.boundingBox();assert.ok(bounds.y+bounds.height<=height+1)
  await noOverflow('director',width);await page.screenshot({path:`${out}/director-${width}.png`})
  await page.getByRole('button',{name:'查看当前任务详情',exact:true}).click()
  await page.getByRole('button',{name:'询问当前任务与依据',exact:true}).click()
  await page.getByRole('button',{name:'场景对话',exact:true}).waitFor()
  await noOverflow('assistant',width);await page.screenshot({path:`${out}/assistant-${width}.png`})
 }
 await page.setViewportSize({width:1366,height:650});await page.goto(url);await closePanel()
 const progress=page.getByRole('region',{name:'当前训练进展',exact:true})
 const started=page.waitForResponse(r=>r.url()===root+'/commands'&&r.request().method()==='POST'&&r.request().postDataJSON().kind==='state')
 await progress.getByRole('button',{name:'开始训练',exact:true}).click();assert.equal((await started).status(),200)
 await page.getByRole('button',{name:'暂停演练',exact:true}).waitFor()
 const paused=page.waitForResponse(r=>r.url()===root+'/commands'&&r.request().method()==='POST'&&r.request().postDataJSON().kind==='state')
 await page.getByRole('button',{name:'暂停演练',exact:true}).click();assert.equal((await paused).status(),200)
 await progress.getByRole('button',{name:'继续训练',exact:true}).waitFor()
 const resumed=page.waitForResponse(r=>r.url()===root+'/commands'&&r.request().method()==='POST'&&r.request().postDataJSON().kind==='state')
 await progress.getByRole('button',{name:'继续训练',exact:true}).click();assert.equal((await resumed).status(),200)
 assert.equal((await body(root)).status,'running')
 await page.getByRole('button',{name:'暂停演练',exact:true}).click()
 await progress.getByRole('button',{name:'继续训练',exact:true}).waitFor()
 await page.getByRole('button',{name:'结束并评分',exact:true}).click()
 const confirmation=page.getByRole('alertdialog',{name:'结束本场并生成评分？',exact:true})
 await confirmation.waitFor();await confirmation.getByRole('button',{name:'结束并评分',exact:true}).click()
 await page.locator('.atlas-replay').waitFor()
 const ended=await body(root);assert.equal(ended.status,'ended')
 await page.getByRole('button',{name:'返回现场',exact:true}).click()
 await progress.getByRole('button',{name:'查看结果与遗漏',exact:true}).waitFor()
 assert.ok((await page.getByRole('button',{name:'打开复盘评分',exact:true}).innerText()).includes('最终评分'))
 await progress.getByRole('button',{name:'查看结果与遗漏',exact:true}).click()
 await page.locator('.atlas-replay').waitFor()
 for(const [width,height]of [[1440,900],[1366,650],[1024,768],[768,1024],[390,844]]){
  await page.setViewportSize({width,height})
  assert.equal(Number(await page.locator('.atlas-replay__score b').innerText()),ended.score.total_score)
  const world=page.locator('.atlas-replay__world .twin-stage__viewport');await world.waitFor()
  const dimensions=await world.boundingBox();assert.ok(dimensions.height>=200,`Replay viewport too small: ${width}, ${dimensions.height}`)
  await noOverflow('replay',width);await page.screenshot({path:`${out}/replay-${width}.png`})
 }
 for(const [width,height]of [[1440,900],[390,844]]){
  await page.setViewportSize({width,height});await page.goto(base+'/projects')
  await page.waitForFunction(()=>{const button=document.querySelector('.training-home__primary');return button&&!button.disabled})
  await page.waitForFunction(()=>!document.querySelector('.training-home')?.textContent.includes('正在读取上次停留的阶段'))
  await noOverflow('home',width);await page.screenshot({path:`${out}/home-${width}.png`})
  await page.getByRole('button',{name:/准备新训练/,exact:false}).first().click()
  await page.getByRole('heading',{name:'场景准备',exact:true}).waitFor()
  await page.getByRole('button',{name:'发布检查',exact:true}).waitFor()
  await page.getByRole('button',{name:'发布检查',exact:true}).click()
  if(width===390){
    const inspector=page.getByRole('complementary',{name:'当前配置参数',exact:true})
    const bounds=await inspector.boundingBox();assert.ok(bounds.y>=0&&bounds.y<height/2,'The chosen preparation step must be visible')
    await page.getByRole('button',{name:'返回三维预览',exact:true}).click()
    const preview=page.getByLabel('三维场景预览',{exact:true})
    const previewBounds=await preview.boundingBox();assert.ok(previewBounds.y>=0&&previewBounds.y<height/2)
    await page.getByRole('button',{name:'发布检查',exact:true}).click()
  }
  await noOverflow('preparation',width);await page.screenshot({path:`${out}/preparation-${width}.png`})
 }
 assert.deepEqual(errors,[])
 writeFileSync(out+'/result.json',JSON.stringify({drillId:drill.id,controls:['start','pause','resume','end'],endedScore:ended.score.total_score,
  scoreMeaning:'Early stop used only for UI state validation; no evacuation decisions were performed',records,pageErrors:errors},null,2))
 console.log(JSON.stringify({controls:['start','pause','resume','end'],pages:records.length,endedScore:ended.score.total_score,pageErrors:errors}))
}finally{await browser.close()}
