import { mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const output = fileURLToPath(new URL('../../output/playwright/director-entry/', import.meta.url))
mkdirSync(output, { recursive:true })
const browser = await chromium.launch({headless:true, executablePath:process.env.QA_BROWSER_PATH})
try {
  const page = await browser.newPage({viewport:{width:1440,height:900}})
  const loadedModels = new Set()
  page.on('response',r=>{if(r.ok() && new URL(r.url()).pathname.endsWith('.glb'))loadedModels.add(new URL(r.url()).pathname)})
  page.setDefaultTimeout(25000)
  page.on('pageerror',e=>console.log('PAGE_ERROR',e.message))
  page.on('response',r=>{if(r.url().includes('/api/v1/') && !r.url().includes('/auth/'))console.log('API',r.status(),new URL(r.url()).pathname)})
  page.on('requestfailed',r=>console.log('FAILED',new URL(r.url()).pathname,r.failure()?.errorText))
  const base=process.env.QA_BASE_URL || 'http://127.0.0.1:5173'
  await page.goto(base+'/login')
  await page.locator('#username').fill('admin')
  await page.locator('#password').fill(process.env.QA_PASSWORD)
  await page.getByRole('button',{name:'进入工作台',exact:true}).click()
  await page.waitForURL('**/projects')
  const token=await page.evaluate(()=>localStorage.getItem('zhiyan_access_token'))
  const result=await page.request.get('http://127.0.0.1:8000/api/v1/communities',{headers:{Authorization:'Bearer '+token}})
  const communities=await result.json()
  const community=communities[0]
  if(!community)throw new Error('No existing community; diagnostic does not create data')
  let injectedFailure=false
  if(process.env.QA_RETRY==='1')await page.route('**/api/v1/drills/*',async route=>{
    if(!injectedFailure && /^\/api\/v1\/drills\/[^/]+$/.test(new URL(route.request().url()).pathname)) {
      injectedFailure=true
      await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'验证：现场服务暂不可用'})})
    } else await route.continue()
  })
  await page.goto(base+'/communities/'+community.id+'/operations')
  if(process.env.QA_RETRY==='1') {
    await page.getByRole('button',{name:'重新读取现场',exact:true}).click()
    console.log('RETRY_CLICKED',injectedFailure)
  }
  let entryFailure
  try {await page.locator('.twin-stage canvas').first().waitFor({state:'visible',timeout:25000});console.log('CANVAS_READY')}
  catch (cause) {entryFailure=cause;console.log('ENTRY_TEXT',(await page.locator('body').innerText()).slice(0,1800))}
  if(!entryFailure) {
    await page.waitForFunction(()=>{const state=document.querySelector('.twin-quality small');return state && state.textContent!=='模型加载中'})
    console.log('MODEL_STATUS',await page.locator('.twin-quality small').getAttribute('aria-label'))
    console.log('GLB_LOADED',loadedModels.size)
  }
  await page.screenshot({path:output+'entry.png'})
  if(process.env.QA_LAYOUT==='1' && !entryFailure) {
    const sizes=await page.locator('.director-actions button, .atlas-timeline-events button, .twin-quality').evaluateAll(items=>items.map(item=>({label:item.textContent.trim().slice(0,18),font:getComputedStyle(item).fontSize})))
    console.log('READING_SIZES',JSON.stringify(sizes))
    await page.setViewportSize({width:390,height:844})
    await page.screenshot({path:output+'mobile.png'})
    const overflows=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth)
    console.log('MOBILE_PAGE_OVERFLOW',overflows)
    if(overflows)throw new Error('Mobile page overflow')
    await page.setViewportSize({width:1440,height:900})
    await page.getByLabel('选择沙盘对象').selectOption('assembly:north')
    await page.getByLabel('集合点到达与核验').waitFor()
    console.log('ASSEMBLY_DETAILS',await page.getByLabel('集合点到达与核验').innerText())
    await page.waitForTimeout(1200)
    await page.screenshot({path:output+'assembly.png'})
    await page.evaluate(()=>document.documentElement.dataset.readingSize='large')
    await page.setViewportSize({width:390,height:844})
    await page.screenshot({path:output+'assembly-mobile-large.png'})
    console.log('LARGE_BODY',await page.locator('.assembly-attendance p').first().evaluate(el=>getComputedStyle(el).fontSize))
  }
  console.log('URL',page.url())
  if(entryFailure)throw entryFailure
} finally {await browser.close()}
