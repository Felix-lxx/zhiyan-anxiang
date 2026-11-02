// Isolated preview data, production preparation UI and real Three.js geometry.
import assert from 'node:assert/strict'
import {kitchenCapabilities,kitchenDefaults,kitchenPreview} from './kitchen-fixture.mjs'
const {default:playwright}=await import(process.env.PLAYWRIGHT_MODULE||'playwright')
const browser=await playwright.chromium.launch({headless:true,...(process.env.QA_BROWSER_PATH?{executablePath:process.env.QA_BROWSER_PATH}:{})})
try{
 const page=await browser.newPage();await page.emulateMedia({reducedMotion:'reduce'})
 let width=1.2,status='open'
 await page.route('**/__scenario_layout__/**',route=>{
  const path=new URL(route.request().url()).pathname
  if(path.endsWith('/scene-templates'))return route.fulfill({json:[{id:'kitchen',code:'kitchen_fire',name:'厨房火灾',defaults:{},capabilities:kitchenCapabilities}]})
  if(path.endsWith('/scenes'))return route.fulfill({json:[{id:'geometry',name:'尺寸联动检查',status:'draft',capabilities:kitchenCapabilities,versions:[{version_number:1,parameters:kitchenDefaults}]}]})
  if(path.endsWith('/map-objects')||path.endsWith('/fire-sources'))return route.fulfill({json:[{id:'home',name:'示例住宅',object_type:'building',floors:4}]})
  if(path.endsWith('/preview')){
   const data=kitchenPreview(kitchenDefaults),start={id:'a',name:'路口甲',x:35,y:60,is_exit:false},end={id:'b',name:'路口乙',x:35,y:75,is_exit:true}
   data.simulation.road_network={nodes:[start,end],edges:[{id:'width-road',name:'联动道路',start,end,width_meters:width,status,risk_score:0,blocked_by_event:false}]}
   return route.fulfill({json:data})
  }
  return route.fulfill({status:404,json:{detail:'Isolated fixture route'}})
 })
 await page.goto((process.env.QA_BASE_URL||'http://127.0.0.1:5181')+'/tests/scenario-preparation.html?scene=geometry&preparation=2')
 const ready=async expected=>{
  await page.waitForFunction(expected=>{
   const stage=document.querySelector('.scene-live-preview .twin-stage'),component=stage?.__vueParentComponent
   return component?.setupState.scene?.getObjectByName('road-pavement')?.geometry.parameters.width===expected
  },expected)
  return page.locator('.scene-live-preview .twin-stage').evaluate(el=>el.__vueParentComponent.uid)
 }
 const initial=await ready(1.2)
 width=4
 await page.getByRole('button',{name:'重新计算预览',exact:true}).click()
 const resized=await ready(4);assert.notEqual(resized,initial,'A changed road footprint must rebuild physical pavement')
 status='blocked'
 await page.getByRole('button',{name:'重新计算预览',exact:true}).click()
 await page.waitForFunction(()=>document.querySelector('.scene-live-preview .twin-stage')?.__vueParentComponent.setupState.roadVisuals.meshes.get('width-road')?.userData.selection.action===undefined)
 assert.equal(await ready(4),resized,'Risk-only changes must retain the existing arena and camera')
 console.log('Road preview: 1.2m to 4m rebuilt pavement; blocked status updated risk without rebuilding the arena')
}finally{await browser.close()}
