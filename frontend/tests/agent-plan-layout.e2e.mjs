// Production components + isolated protocol fixture. Backend execution is verified separately.
import assert from 'node:assert/strict'
import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
const { default: playwright } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await playwright.chromium.launch({headless:true,...(process.env.QA_BROWSER_PATH?{executablePath:process.env.QA_BROWSER_PATH}:{})})
const output=resolve('../output/playwright/agent-plans');mkdirSync(output,{recursive:true})
try {
  const page=await browser.newPage(), errors=[]
  page.on('pageerror',error=>errors.push(error.message))
  let run=null
  const candidate=id=>({id,title:id==='one'?'路径优先分流':'另一出口对照',can_apply:true,reason:'确认后执行，护送按资源分批。',coverage:'30 秒居民与首批护送预演。',forecast_at:0,forecast_seconds:30,
    geometry_issues:[{edge_id:'invalid-link',name:'三号楼门前连接',reason:'通道与楼体或人员净距范围相交，请调整地图后新建场次。'}],
    robot_support:{target:'示例楼栋东侧楼门广播点',can_apply:true,notice:'居民独立撤离；机器人到位后广播，不替代人工任务签核。',duration_seconds:24,battery_required:5,battery_available:82,route_points:[{x:50,y:70},{x:20,y:45}]},
    assignments:[{id:'resident-test',label:'测试居民',exit:'north',vulnerable:false,route_reachable:true,route_points:[{x:20,y:70},{x:20,y:45}]}],
    metrics:{north:1,south:0,unreachable:0,arrived:0,exposed:0,queue_seconds:8,score:60,score_delta:2}})
  await page.route('**/__layout_api__/**',async route=>{
    const request=route.request(), path=new URL(request.url()).pathname
    if(path.endsWith('/assistant/status'))return route.fulfill({json:{configured:false,model:null}})
    if(path.endsWith('/actions')){
      const body=request.postDataJSON()
      run={...run,status:body.action==='stop'?'stopped':'waiting',reason:'居民正在撤离，机器人广播等待到位。',approved_revision:1,selected_candidate:'one',candidates:[],steps:[
        {id:'step',label:'居民分流 · 北门 · 1 人',resident_ids:['resident-test'],command_id:'agent-step',exit:'north',action:'evacuate',status:'executing',reason:'正沿连续通道撤离',progress:.3,
          execution:{total:1,arrived:0,blocked:0,queued:1,remaining_details:0,command_recorded:true,idle_seconds:4,stalled:false,
            attention:[{id:'resident-test',label:'测试居民',location:'三号楼二层东侧走廊 → 二层楼梯入口',behavior:'前方人员通过后继续前进',arrived:false,blocked:false,counted:false,queue_seconds:18,smoke_exposure:3,bottleneck:'二层楼梯',staff_name:'模拟值守员 1',responsible:'物业测试员',escort_state:'approaching'}],
            evidence:[{id:'receipt-1',sequence:12,at_seconds:15,message:'居民分流指令已受理，沿北侧通道撤离。'}]}},
        {id:'move',kind:'robot.command',label:'机器人前往示例楼栋东侧楼门广播点',resident_ids:[],command_id:'agent-move',depends_on:[],status:'executing',reason:'机器人正沿道路逐段前往目标。',progress:.4},
        {id:'broadcast',kind:'robot.command',label:'机器人到位广播',resident_ids:[],command_id:'agent-broadcast',depends_on:['move'],status:'waiting',reason:'等待本计划机器人真实到位，居民疏散同步进行。',progress:0}]}
      return route.fulfill({json:run})
    }
    if(request.method()==='POST'){
      run={id:'run',goal:request.postDataJSON().goal,status:'awaiting_approval',reason:'方案已计算，尚未执行。',revision:1,approved_revision:null,selected_candidate:null,planner:'local',planner_notice:'未调用大模型',at_seconds:0,
        scope:{resident_ids:['resident-test'],building_id:'home',building_name:'示例楼栋',priority_assist:true,robot_broadcast:true,completion:'到场后由参演者清点'},candidates:[candidate('one'),candidate('two')],steps:[],summary:{total:1,arrived:0,counted:0,assisted:0,exposed:0},history:[]}
      return route.fulfill({json:run})
    }
    return route.fulfill({json:{buildings:[{id:'home',name:'示例楼栋'}],runs:run?[run]:[],drill_status:'running'}})
  })
  await page.goto((process.env.QA_BASE_URL||'http://127.0.0.1:5173')+'/tests/arena-recovery.html?rescue=1')
  await page.locator('canvas').first().waitFor({timeout:30000})
  for(const [width,height] of [[1440,900],[1366,650],[1024,800],[390,844]]){
    run=null
    await page.evaluate(()=>window.arenaQA.assistant(false))
    await page.setViewportSize({width,height})
    await page.evaluate(()=>window.arenaQA.assistant(true))
    const assistant=page.getByLabel('场景 AI 助手',{exact:true})
    await assistant.getByRole('button',{name:'目标计划',exact:true}).click()
    await assistant.getByRole('combobox').selectOption('home')
    await assistant.getByLabel('机器人到楼门广播',{exact:true}).check()
    await assistant.getByRole('button',{name:'生成并比较方案',exact:true}).click()
    const approve=assistant.getByRole('button',{name:'确认方案并执行',exact:true})
    await approve.waitFor()
    assert.equal(await assistant.evaluate(el=>el.scrollWidth>el.clientWidth+1),false)
    await assistant.getByRole('button',{name:'在三维现场预览路线'}).first().click()
    if(width<=760){
      assert.equal(await assistant.isVisible(),false,'Mobile preview returns to the scene')
      await page.evaluate(()=>window.arenaQA.assistant(true))
      await assistant.getByRole('button',{name:'目标计划',exact:true}).click()
      await approve.waitFor()
    }
    assert.equal(await page.evaluate(()=>window.arenaQA ? document.querySelectorAll('.scene-assistant').length:0),1)
    await approve.scrollIntoViewIfNeeded()
    const target=await approve.boundingBox(),close=await assistant.getByRole('button',{name:'关闭 AI 助手'}).boundingBox()
    assert.ok(target.y>=close.y+close.height,'Approval does not overlap the fixed header')
    await page.screenshot({path:resolve(output,`proposal-${width}.png`)})
    const check=assistant.locator('summary').first()
    await check.click()
    const detail=assistant.locator('.agent-workspace__geometry').first()
    assert.ok(await detail.getByText('三号楼门前连接',{exact:true}).isVisible())
    assert.ok(await detail.evaluate(el=>el.scrollWidth<=el.clientWidth+1))
    await page.screenshot({path:resolve(output,`geometry-${width}.png`)})
    await approve.scrollIntoViewIfNeeded()
    await approve.click()
    await assistant.getByText('正沿连续通道撤离',{exact:true}).waitFor()
    await assistant.getByText('等待本计划机器人真实到位，居民疏散同步进行。',{exact:true}).waitFor()
    assert.equal(await assistant.getByRole('button',{name:'定位机器人',exact:true}).count(),2)
    const resident=assistant.getByRole('button',{name:'定位测试居民',exact:true})
    await resident.scrollIntoViewIfNeeded()
    assert.ok(await resident.isVisible())
    assert.ok(await assistant.locator('.agent-workspace__detail').evaluate(el=>el.scrollWidth<=el.clientWidth+1))
    await page.screenshot({path:resolve(output,`monitor-${width}.png`)})
    await resident.click()
    assert.equal(await assistant.count(),0,'Resident action returns to the actual 3D viewport')
    await page.locator('.resident-pov-hud').waitFor()
    assert.equal(await page.locator('.twin-object-nav').count(),0,'Object picker cannot overlap the resident inspector')
    await page.screenshot({path:resolve(output,`staff-route-${width}.png`)})
    await page.evaluate(()=>window.arenaQA.assistant(true))
    await assistant.getByRole('button',{name:'目标计划',exact:true}).click()
    await assistant.getByText('正沿连续通道撤离',{exact:true}).waitFor()
    await assistant.getByRole('button',{name:'停止后续自动下令'}).scrollIntoViewIfNeeded()
    await page.screenshot({path:resolve(output,`execution-${width}.png`)})
    await assistant.getByRole('button',{name:'停止后续自动下令'}).click()
    await assistant.getByText('已停止自动下令',{exact:true}).waitFor()
  }
  assert.deepEqual(errors,[])
  console.log(JSON.stringify({checks:['目标生成→路线预览→确认→人员定位与依据→停止','1440/1366短屏/1024/390 面板内部滚动，无横向溢出','确认按钮与固定标题不重叠'],errors,output},null,2))
}finally{await browser.close()}
