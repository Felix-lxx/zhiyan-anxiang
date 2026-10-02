// Real local API and isolated, explicitly named QA scene. Never modifies existing scenes.
// QA_PASSWORD, QA_BASE_URL, QA_API_URL, PLAYWRIGHT_MODULE and QA_BROWSER_PATH are environment options.
import assert from 'node:assert/strict'
import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
const { default: playwright } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
assert.ok(process.env.QA_PASSWORD, 'QA_PASSWORD is required')
const base=process.env.QA_BASE_URL||'http://127.0.0.1:5174'
const apiRoot=process.env.QA_API_URL||'http://127.0.0.1:8011/api/v1'
const artifacts=resolve(process.env.QA_ARTIFACT_DIR||'../.tmp/atlas-review')
mkdirSync(artifacts,{recursive:true})
const browser=await playwright.chromium.launch({headless:true,...(process.env.QA_BROWSER_PATH?{executablePath:process.env.QA_BROWSER_PATH}:{})})
const context=await browser.newContext({viewport:{width:1672,height:941}})
const page=await context.newPage(), errors=[], checks=[]
page.setDefaultTimeout(12000);page.on('pageerror',e=>errors.push(e.message))
let token,drill,scene,community,phone
async function api(path,method='GET',data){const r=await context.request.fetch(apiRoot+path,{method,headers:token?{Authorization:`Bearer ${token}`}:{},...(data?{data}:{})});assert.ok(r.ok(),`${method} ${path}: ${r.status()} ${r.ok()?'':await r.text()}`);return r.json()}
async function screenshot(name,p=page){await p.screenshot({path:resolve(artifacts,name+'.png'),fullPage:true})}
async function noOverflow(p){assert.ok(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'horizontal overflow')}
try{
 await page.goto(base+'/login');await page.locator('#username').fill('admin');await page.locator('#password').fill(process.env.QA_PASSWORD)
 await page.getByRole('button',{name:'显示密码'}).click();assert.equal(await page.locator('#password').getAttribute('type'),'text');await page.getByRole('button',{name:'隐藏密码'}).click()
 for(const width of [390,1280,1366,1440,1672,1920]){await page.setViewportSize({width,height:width===390?844:941});await noOverflow(page);if([390,1672].includes(width))await screenshot('login-'+width)}
 await page.setViewportSize({width:1672,height:941});await page.getByRole('button',{name:'进入工作台',exact:true}).click();await page.waitForURL('**/projects');await page.getByText('系统在线',{exact:true}).waitFor();token=await page.evaluate(()=>localStorage.getItem('zhiyan_access_token'));await screenshot('home-1672');await noOverflow(page);checks.push('Login, password toggle, six viewport widths, real home data')
 const communities=await api('/communities');community=communities[0];assert.ok(community)
 const templates=await api('/scene-templates'), objects=await api('/communities/'+community.id+'/map-objects')
 scene=await api('/communities/'+community.id+'/scenes','POST',{template_id:templates.find(t=>t.code==='night_charging_shed_fire').id,name:'UI 自动验收 '+new Date().toISOString().slice(0,16)})
 await api('/scenes/'+scene.id+'/charging-shed-parameters','PATCH',{fire_source_object_id:objects.find(o=>o.object_type==='charging_shed').id,start_time:'20:15',wind_direction:'微风',resident_count:18,hydrant_status:'available',south_lane_status:'open',stair_width:1.2})
 const decision=await api('/scenes/'+scene.id+'/decision-points','POST',{name:'火情确认后切断电源',trigger_condition:'确认火情后',responsible_role:'物业/网格员',time_limit_seconds:600,options:[{label:'切断充电棚电源',consequence:'核验充电棚电源切断'},{label:'等候现场核查',consequence:'持续确认'}]})
 await api('/decision-options/'+decision.options[0].id+'/execute','POST')
 await page.goto(base+'/communities/'+community.id+'/scenes?scene='+scene.id);await page.locator('.scene-live-preview canvas').first().waitFor();await screenshot('scene-1672')
 await page.getByRole('button',{name:'运行校验',exact:true}).click();await page.getByText('校验通过，可以冻结',{exact:true}).waitFor();checks.push('Scene preview and validation')
 await api('/scenes/'+scene.id+'/publish','POST');drill=await api('/scenes/'+scene.id+'/drills','POST',{name:'UI 闭环验收 '+new Date().toISOString().slice(0,16),time_scale:2})
 const operations=base+'/communities/'+community.id+'/operations?scene='+scene.id+'&drill='+drill.id
 await page.goto(operations);await page.getByRole('button',{name:'开始推演',exact:true}).click();await page.getByRole('button',{name:'暂停演练',exact:true}).waitFor();await screenshot('director-1672')
 const phoneContext=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});phone=await phoneContext.newPage();phone.setDefaultTimeout(12000);phone.on('pageerror',e=>errors.push(e.message))
 await phone.goto(base+'/participant/'+drill.id+'?code='+drill.id.slice(-6).toUpperCase());await phone.locator('#participant-name').fill('UI 验收物业组');await phone.getByRole('button',{name:'登记并接收任务'}).click()
 await phone.getByRole('button',{name:'接收任务',exact:true}).waitFor({timeout:35000});await phone.getByRole('button',{name:'接收任务',exact:true}).click();await phone.getByRole('button',{name:'回执已到达目标'}).click();await phone.locator('.task-workflow textarea').fill('已核查并关闭充电棚电源，确认断电完成。');await phone.getByRole('button',{name:'提交核验证据'}).click({timeout:20000});await phone.getByText('结果证据：已核查并关闭充电棚电源，确认断电完成。').waitFor();await noOverflow(phone);await screenshot('participant-390',phone)
 await phone.getByRole('button',{name:/报告异常/}).click();await phone.getByPlaceholder('请说明所在位置、遇到的阻碍及需要的支援').fill('北侧通道需补充引导人员，请导演协调。');await phone.getByRole('button',{name:'发送给导演'}).click();await phone.getByText('反馈已写入本场证据，导演台将同步更新',{exact:true}).waitFor();checks.push('Mobile join, accept, arrive, submit persisted evidence, abnormal report')
 await page.getByRole('button',{name:'指挥',exact:true}).click();await page.locator('.twin-object-nav select').selectOption({label:'北门主通道（畅通）'});await page.getByRole('button',{name:'在此注入事件',exact:true}).click();await page.getByRole('button',{name:'确认执行',exact:true}).waitFor();await screenshot('director-spatial-preview');await page.getByRole('button',{name:'确认执行',exact:true}).click();await page.getByRole('button',{name:'解除此路段封锁',exact:true}).waitFor();checks.push('Road selection, server preview, confirmed closure')
 await page.getByRole('button',{name:'暂停演练',exact:true}).click();await page.getByRole('button',{name:'复盘',exact:true}).click();await page.locator('.atlas-replay').waitFor();await page.getByRole('button',{name:'向前十秒'}).click();await screenshot('replay-1672');await noOverflow(page)
 for(const width of [1280,1366,1440,1920,390]){await page.setViewportSize({width,height:width===390?844:941});await noOverflow(page)}
 await page.setViewportSize({width:1672,height:941});await page.getByRole('button',{name:'创建决策分支',exact:true}).click();await page.waitForURL(url=>url.searchParams.get('drill')!==drill.id);await page.getByRole('button',{name:'继续演练',exact:true}).waitFor();const branchId=new URL(page.url()).searchParams.get('drill');assert.notEqual(branchId,drill.id);checks.push('Snapshot replay and editable decision branch')
 await page.goto(operations);await page.getByRole('button',{name:'结束并评分'}).click();await page.getByRole('alertdialog').getByRole('button',{name:'结束并评分'}).click();await page.locator('.atlas-replay').waitFor();const downloadPromise=page.waitForEvent('download');await page.getByRole('button',{name:'导出复盘报告'}).click();const download=await downloadPromise;assert.ok(download.suggestedFilename().endsWith('.json'));checks.push('End, frozen score, real report download')
 assert.deepEqual(errors,[]);console.log(JSON.stringify({checks,errors,scene_id:scene.id,drill_id:drill.id,artifacts},null,2))
}catch(error){await screenshot('failure').catch(()=>{});if(phone)await screenshot('phone-failure',phone).catch(()=>{});throw error}
finally{if(drill&&token){const state=await api('/drills/'+drill.id).catch(()=>null);if(state?.status==='running')await api('/drills/'+drill.id+'/state','PATCH',{action:'pause'}).catch(()=>{})}await browser.close()}
