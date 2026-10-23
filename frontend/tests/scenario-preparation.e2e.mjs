import assert from 'node:assert/strict'
import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
const { default:playwright }=await import(process.env.PLAYWRIGHT_MODULE||'playwright')
const browser=await playwright.chromium.launch({headless:true,...(process.env.QA_BROWSER_PATH?{executablePath:process.env.QA_BROWSER_PATH}:{})})
const output=resolve('../output/playwright/scenario-preparation');mkdirSync(output,{recursive:true})
const capabilities={code:'night_charging_shed_fire',contract_version:1,title:'夜间充电棚火灾',status:'available',notice:'可配置充电棚起火点、居民和通道，预览后发布并进入演练。',source_types:['charging_shed'],location_kinds:['object'],features:['室外火情推演','楼内外连续疏散','机器人协同','集合清点与复盘'],parameter_schema:'charging_shed.v1',environment_model:'outdoor_rules.v1',can_create:true,can_configure:true,can_preview:true,can_publish:true,can_run:true}
const planned={...capabilities,code:'kitchen_fire',title:'住宅厨房火灾',status:'planned',notice:'建设中：待接入房间选点、分区烟气和室内任务；暂不可创建或运行该案例。',can_create:false,can_configure:false,can_preview:false,can_publish:false,can_run:false,features:[],parameter_schema:null,environment_model:null}
const templates=[{id:'shed',code:'night_charging_shed_fire',name:'夜间电动自行车充电棚火灾',description:'室外案例',defaults:{},capabilities},{id:'kitchen',code:'kitchen_fire',name:'居民厨房火灾',description:'室内案例',defaults:{},capabilities:planned}]
try{
  const page=await browser.newPage();const errors=[];page.on('pageerror',error=>errors.push(error.message))
  let scenes=[];let creates=0;let previewReads=0
  await page.route('**/__scenario_layout__/**',route=>{
    const path=new URL(route.request().url()).pathname
    if(path.endsWith('/scene-templates'))return route.fulfill({json:templates})
    if(path.endsWith('/map-objects'))return route.fulfill({json:[{id:'source',name:'南侧充电棚',object_type:'charging_shed'}]})
    if(path.endsWith('/fire-sources'))return route.fulfill({json:[{id:'source',name:'南侧充电棚',object_type:'charging_shed'}]})
    if(path.endsWith('/preview')){previewReads++;return route.fulfill({status:422,json:{detail:'尚未保存场景参数，请核对后保存。'}})}
    if(path.endsWith('/scenes')){
      if(route.request().method()==='POST'){
        assert.equal(route.request().postDataJSON().template_id,'shed')
        creates++;const item={id:'case-'+creates,name:route.request().postDataJSON().name,status:'draft',capabilities,versions:[{version_number:1,parameters:{fire_source_type:'charging_shed',start_time:'20:15',wind_direction:'微风'}}]};scenes=[item,...scenes];return route.fulfill({json:item})
      }
      return route.fulfill({json:scenes})
    }
    return route.fulfill({status:404,json:{detail:'Fixture route not defined'}})
  })
  const base=process.env.QA_BASE_URL||'http://127.0.0.1:5173'
  for(const [width,height] of [[1440,900],[1366,650],[390,844]]){
    scenes=[];await page.setViewportSize({width,height});await page.goto(base+'/tests/scenario-preparation.html')
    const choices=page.getByRole('group',{name:'选择演练案例'})
    await choices.waitFor();assert.ok(await choices.getByRole('radio').nth(0).isChecked());assert.ok(await choices.getByRole('radio').nth(1).isDisabled())
    assert.ok(await choices.getByText('建设中',{exact:true}).isVisible())
    await page.getByLabel('场景名称',{exact:true}).fill('契约布局核对')
    const create=page.getByRole('button',{name:'创建场景草稿',exact:true});await create.scrollIntoViewIfNeeded()
    assert.ok(await page.locator('main').evaluate(el=>el.scrollWidth<=el.clientWidth+1))
    await page.screenshot({path:resolve(output,`cases-${width}.png`)})
    await create.click();await page.getByRole('button',{name:'新建场景',exact:true}).waitFor()
    await page.getByRole('button',{name:'新建场景',exact:true}).click();await choices.waitFor()
    assert.ok(await choices.getByRole('radio').nth(0).isChecked())
  }
  const before=previewReads
  scenes=[{id:'legacy',name:'旧厨房配置',status:'published',capabilities:planned,versions:[{version_number:1,parameters:{}}]}]
  await page.setViewportSize({width:1366,height:650});await page.goto(base+'/tests/scenario-preparation.html?scene=legacy')
  const blocked=page.getByLabel('案例支持情况',{exact:true});await blocked.waitFor()
  assert.ok(await page.getByRole('button',{name:'演练推演',exact:true}).isDisabled())
  assert.ok(await page.getByRole('button',{name:'保存草稿',exact:true}).isDisabled())
  assert.equal(previewReads,before,'Unsupported case must not request a charging-shed preview')
  assert.ok(await blocked.evaluate(el=>el.scrollWidth<=el.clientWidth+1))
  await page.screenshot({path:resolve(output,'legacy-blocked.png')})
  assert.deepEqual(errors,[])
  console.log(JSON.stringify({creates,checks:['可运行案例创建','建设中案例禁用','新建后返回已有场景','旧厨房配置阻断','桌面/短屏/手机无横向溢出'],errors,output},null,2))
}finally{await browser.close()}
