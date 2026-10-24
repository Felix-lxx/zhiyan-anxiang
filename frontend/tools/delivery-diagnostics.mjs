// Local, read-only browser layout inspection. Credentials come from QA env.
import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
const {default:pw}=await import(process.env.PLAYWRIGHT_MODULE||'playwright')
const browser=await pw.chromium.launch({headless:true,executablePath:process.env.QA_BROWSER_PATH})
const output=resolve('../output/playwright/delivery-diagnostics');mkdirSync(output,{recursive:true})
try {
 const context=await browser.newContext();const page=await context.newPage()
 await context.request.post(process.env.QA_API_URL+'/auth/login',{data:{username:'admin',password:process.env.QA_PASSWORD}})
 await page.goto(process.env.QA_BASE_URL+'/projects');await page.locator('.atlas-case__details').waitFor()
 await page.setViewportSize({width:360,height:844})
 console.log(JSON.stringify(await page.evaluate(()=>[...document.querySelectorAll('body *')].filter(el=>{const r=el.getBoundingClientRect();return r.width&&r.height&&r.right>innerWidth+1}).map(el=>({tag:el.tagName,cl:el.className,rect:el.getBoundingClientRect().toJSON(),text:el.textContent?.slice(0,60)})).slice(0,25)),null,2))
 await page.screenshot({path:resolve(output,'home-360.png'),fullPage:true})
 await page.goto(process.env.QA_BASE_URL+'/tests/arena-recovery.html?rescue=1');await page.locator('canvas').first().waitFor()
 await page.evaluate(()=>{window.arenaQA.rescue('spray');window.arenaQA.vehicles(false)})
 await page.setViewportSize({width:1440,height:900})
 await page.getByRole('button',{name:'查看楼内透视',exact:true}).click()
 await page.waitForTimeout(500)
 console.log('CUTAWAY',await page.getByRole('group',{name:'现场显示与车辆工具'}).innerText())
 await page.screenshot({path:resolve(output,'cutaway.png')})
} finally {await browser.close()}
