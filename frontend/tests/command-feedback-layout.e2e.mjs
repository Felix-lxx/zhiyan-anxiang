import assert from 'node:assert/strict'
import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
const { default:playwright }=await import(process.env.PLAYWRIGHT_MODULE||'playwright')
const browser=await playwright.chromium.launch({headless:true,...(process.env.QA_BROWSER_PATH?{executablePath:process.env.QA_BROWSER_PATH}:{})})
const output=resolve('../output/playwright/command-feedback');mkdirSync(output,{recursive:true})
const receipt={id:'agent-550e8400-e29b-41d4-a716-446655440000',kind:'residents.assign',label:'重点人员护送与北侧通道分流',actor:'社区演练组织员',accepted_at:42,status:'blocked',progress:.25,reason:'值守员正前往三号楼二层会合，前方楼梯有人排队，等待通过后继续。',remaining_seconds:null,resident_ids:['resident-test'],event_ids:['event-test'],score_before:60,score_after_acceptance:61,completed_count:1,selected_count:4,origin:{kind:'agent',plan_id:'550e8400-e29b-41d4-a716-446655440000',revision:3,step_id:'d880322f-ab49-4057-87d9-f429d683b372'}}
try{
  const page=await browser.newPage();const errors=[];page.on('pageerror',error=>errors.push(error.message))
  await page.goto((process.env.QA_BASE_URL||'http://127.0.0.1:5181')+'/tests/arena-recovery.html?rescue=1')
  await page.locator('canvas').first().waitFor({timeout:30000})
  for(const [width,height] of [[1440,900],[1366,650],[390,844]]){
    await page.setViewportSize({width,height})
    await page.evaluate(value=>window.arenaQA.commands(value),[receipt,{...receipt,id:'director-robot-001',kind:'robot.command',status:'queued',label:'机器人前往三号楼入口',reason:'等待前一巡检任务完成，随后沿服务端路线前往。',selected_count:0,origin:{kind:'director',plan_id:null,revision:null,step_id:null}},{...receipt,id:'old-receipt',status:'completed',origin:null}])
    const panel=page.getByLabel('指令执行进度',{exact:true})
    await panel.waitFor();await panel.getByText('智能体计划 · 批准版本 3 · 社区演练组织员',{exact:true}).waitFor()
    assert.ok(await panel.getByText('人工下令 · 社区演练组织员',{exact:true}).isVisible())
    assert.ok(await panel.getByText('执行受阻',{exact:true}).isVisible())
    const detail=panel.locator('details').first()
    if(await detail.getAttribute('open')===null)await detail.locator('summary').click()
    await detail.scrollIntoViewIfNeeded()
    assert.ok(await detail.getByText(receipt.origin.plan_id,{exact:true}).isVisible())
    assert.ok(await panel.evaluate(el=>el.scrollWidth<=el.clientWidth+1))
    assert.ok(await detail.evaluate(el=>el.scrollWidth<=el.clientWidth+1))
    await page.screenshot({path:resolve(output,`receipts-${width}.png`)})
    await panel.getByRole('button',{name:'指令记录 3',exact:true}).click()
    assert.equal(await panel.locator('ol>li').count(),3)
  }
  assert.deepEqual(errors,[])
  console.log(JSON.stringify({checks:['人工/智能体来源与真实状态同时展示','长指令/计划编号换行','旧回执可读','桌面/短屏/手机无横向溢出'],errors,output},null,2))
}finally{await browser.close()}
