// Real API authentication; failure fixtures are local to this browser context.
import assert from 'node:assert/strict'
import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
const { default: playwright } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
assert.ok(process.env.QA_PASSWORD, 'QA_PASSWORD required for isolated acceptance')
const base = process.env.QA_BASE_URL || 'http://127.0.0.1:5173'
const output = resolve('../output/playwright/entry-delivery')
mkdirSync(output, { recursive:true })
const browser = await playwright.chromium.launch({ headless:true, ...(process.env.QA_BROWSER_PATH ? { executablePath:process.env.QA_BROWSER_PATH } : {}) })
try {
  const page = await browser.newPage(), errors=[]
  page.on('pageerror', error=>errors.push(error.message))
  await page.goto(base+'/login')
  await page.getByRole('button', { name:'重新检查服务状态' }).getByText('系统正常', {exact:false}).waitFor()
  const checkBounds = async () => {
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1), 'No page overflow')
    for (const selector of ['.atlas-login__brand','.atlas-health','.atlas-login__submit']) {
      const r=await page.locator(selector).boundingBox()
      assert.ok(r&&r.x>=0&&r.x+r.width<=await page.evaluate(()=>innerWidth)+1,selector+' stays inside viewport')
    }
    const a=await page.locator('.atlas-login__brand').boundingBox(), b=await page.locator('.atlas-health').boundingBox()
    assert.ok(b.y>=a.y+a.height,'Service status does not overlap the brand')
  }
  for (const width of [360,390,768,1024,1440]) {
    await page.setViewportSize({width,height:width<700?844:900})
    await checkBounds()
    await page.screenshot({path:resolve(output,`login-${width}.png`),fullPage:true})
  }
  await page.setViewportSize({width:1024,height:650})
  await page.evaluate(()=>document.documentElement.style.fontSize='20px')
  await checkBounds()
  await page.evaluate(()=>document.documentElement.style.fontSize='')
  const fail=route=>route.fulfill({status:401,json:{detail:'验收：账号或密码错误'}})
  await page.route('**/auth/login',fail)
  await page.locator('#username').fill(process.env.QA_USERNAME||'admin')
  await page.locator('#password').fill(process.env.QA_PASSWORD)
  await page.getByRole('button',{name:'进入工作台',exact:true}).click()
  await page.getByRole('alert').filter({hasText:'验收：账号或密码错误'}).waitFor()
  await page.unroute('**/auth/login',fail)
  await page.getByRole('button',{name:'进入工作台',exact:true}).click()
  await page.waitForURL('**/projects')
  await page.reload()
  await page.locator('.atlas-case__details').waitFor()
  assert.equal(await page.evaluate(()=>localStorage.getItem('zhiyan_access_token')),null)
  for(const width of [360,390,768,1024,1440]) {
    await page.setViewportSize({width,height:width<700?844:900})
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1))
    await page.screenshot({path:resolve(output,`home-${width}.png`),fullPage:true})
  }
  assert.deepEqual(errors,[])
  console.log(JSON.stringify({checks:['5 viewport widths, no brand/status overlap','Injected failure recovery and real login','HttpOnly refresh after reload without localStorage token','Home responsive bounds'],errors,output},null,2))
} finally { await browser.close() }
