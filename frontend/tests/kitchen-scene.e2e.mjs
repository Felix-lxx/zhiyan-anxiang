import assert from 'node:assert/strict'
import {mkdirSync} from 'node:fs'
import {resolve} from 'node:path'
import {PerspectiveCamera,Vector3} from '../node_modules/three/build/three.module.js'
import ts from 'typescript'
import {readFile} from 'node:fs/promises'
import {pathToFileURL} from 'node:url'
const geometrySource=await readFile(new URL('../src/three/indoorGeometry.ts',import.meta.url),'utf8')
const compiled=ts.transpileModule(geometrySource,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText
const threeUrl=pathToFileURL(resolve('node_modules/three/build/three.module.js')).href
const {indoorCameraOffset}=await import('data:text/javascript;base64,'+Buffer.from(compiled.replace("from 'three'",`from '${threeUrl}'`)).toString('base64'))
import {kitchenCapabilities,kitchenDefaults,kitchenPreview} from './kitchen-fixture.mjs'
const {default:playwright}=await import(process.env.PLAYWRIGHT_MODULE||'playwright')
const browser=await playwright.chromium.launch({headless:true,...(process.env.QA_BROWSER_PATH?{executablePath:process.env.QA_BROWSER_PATH}:{})})
const output=resolve('../output/playwright/kitchen-scene');mkdirSync(output,{recursive:true})
try{
 const page=await browser.newPage();await page.emulateMedia({reducedMotion:'reduce'});const errors=[];page.on('pageerror',error=>errors.push(error.message))
 let saved={...kitchenDefaults},writes=0
 const scene=()=>({id:'kitchen-scene',name:'厨房案例 · 布局验收',status:'draft',capabilities:kitchenCapabilities,versions:[{version_number:1,parameters:saved}]})
 await page.route('**/__scenario_layout__/**',route=>{
  const path=new URL(route.request().url()).pathname
  if(path.endsWith('/scene-templates'))return route.fulfill({json:[{id:'kitchen',code:'kitchen_fire',name:'住宅厨房火灾',description:'厨房室内案例',defaults:{},capabilities:kitchenCapabilities}]})
  if(path.endsWith('/scenes'))return route.fulfill({json:[scene()]})
  if(path.endsWith('/map-objects')||path.endsWith('/fire-sources'))return route.fulfill({json:[{id:'home',name:'示例住宅楼',object_type:'building',floors:4}]})
  if(path.endsWith('/preview'))return route.fulfill({json:kitchenPreview(route.request().method()==='POST'?route.request().postDataJSON():saved)})
  if(path.endsWith('/parameters')){saved=route.request().postDataJSON();writes++;return route.fulfill({json:scene()})}
  return route.fulfill({status:404,json:{detail:'Fixture route not defined'}})
 })
 const base=process.env.QA_BASE_URL||'http://127.0.0.1:5181'
 for(const [width,height] of [[1440,900],[1366,650],[390,844]]){
  saved={...kitchenDefaults};await page.setViewportSize({width,height});await page.goto(base+'/tests/scenario-preparation.html?scene=kitchen-scene&preparation=2')
  const floor=page.getByLabel('起火楼层',{exact:true});await floor.waitFor();await floor.selectOption('3')
  const room=page.getByLabel('起火厨房',{exact:true});await room.selectOption('west')
  const save=page.getByRole('button',{name:'保存场景参数',exact:true});await save.click();await page.getByText('参数已保存，新场次将冻结此火点。',{exact:true}).waitFor()
  assert.equal(saved.fire_floor,3);assert.equal(saved.fire_room,'west')
  assert.ok(await page.locator('main').evaluate(el=>el.scrollWidth<=el.clientWidth+1))
  const canvas=page.locator('.scene-live-preview canvas').last();await canvas.scrollIntoViewIfNeeded();await canvas.waitFor()
  const bounds=await canvas.boundingBox();assert.ok(bounds.height>=200)
  const elevation=3*3.2-3.02
  const camera=new PerspectiveCamera(48,bounds.width/bounds.height,.1,400)
  camera.position.copy(indoorCameraOffset(16,10,camera.aspect)).add(new Vector3(0,elevation,0));camera.lookAt(0,elevation,0);camera.updateMatrixWorld()
  const selectedRoom=kitchenPreview(saved).simulation.environment.indoor.zones.find(zone=>zone.id===`indoor:home:${saved.fire_floor}:east`)
  const point=new Vector3(selectedRoom.x-50,elevation+.03,selectedRoom.y-50).project(camera)
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))
  await page.mouse.click(bounds.x+(point.x+1)*bounds.width/2,bounds.y+(1-point.y)*bounds.height/2)
  await page.waitForFunction(()=>document.querySelector('#fire-room')?.value==='east')
  await page.getByRole('button',{name:'撤销火点选择',exact:true}).click()
  assert.equal(await room.inputValue(),'west')
  await page.screenshot({path:resolve(output,`prepare-${width}.png`),fullPage:true})
  await page.goto(base+'/tests/kitchen-director.html')
  const control=page.getByRole('button',{name:'楼内烟气与门控',exact:true});await control.waitFor();await control.click()
  const panel=page.getByRole('region',{name:'楼内烟气与房门'});await panel.waitFor()
  const close=panel.getByRole('button',{name:/^关闭.*房门$/}).first();await close.click()
  await panel.getByRole('button',{name:/^打开.*房门$/}).first().waitFor()
  assert.ok(await panel.evaluate(el=>el.scrollWidth<=el.clientWidth+1))
  const drawer=await page.getByRole('dialog').boundingBox()
  assert.ok(drawer.y>=64&&drawer.y+drawer.height<=height+1)
  if(width>1100){
    const stage=await page.locator('.director-stage').boundingBox()
    assert.ok(stage.x+stage.width<=drawer.x+1,'Scene must reserve space for the task workspace')
  }else assert.ok(drawer.width>=width-20,'Phone task panel must use the available width')
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))
  await page.screenshot({path:resolve(output,`doors-${width}.png`),fullPage:true})
  await panel.getByRole('button',{name:'进入处置',exact:true}).click()
  await page.getByRole('progressbar',{name:'到位回执后的处置计时'}).waitFor()
  assert.equal(await page.getByRole('dialog').count(),1)
  assert.ok(await page.locator('.task-workflow').evaluate(el=>el.scrollWidth<=el.clientWidth+1))
  await page.screenshot({path:resolve(output,`operation-${width}.png`),fullPage:true})
  await page.getByRole('button',{name:'返回室内现场'}).click()
  await panel.waitFor()
 }
 assert.deepEqual(errors,[]);console.log(JSON.stringify({writes,checks:['厨房楼层房间配置','保存恢复','真实三维厨房与分区渲染','门控面板状态交互','桌面短屏手机布局'],errors,output},null,2))
}finally{await browser.close()}
