import assert from 'node:assert/strict'
import { mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ headless: true, ...(process.env.QA_BROWSER_PATH ? { executablePath: process.env.QA_BROWSER_PATH } : {}) })
const output = fileURLToPath(new URL('../../output/playwright/actors/', import.meta.url))
mkdirSync(output, { recursive: true })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  const errors = []; page.on('pageerror', error => errors.push(error.message))
  const url = (process.env.QA_BASE_URL || 'http://127.0.0.1:5173') + '/tools/actors-preview.html'
  await page.goto(url); await page.waitForFunction(() => window.actorPreview?.ready)
  await page.waitForTimeout(600)
  const stats = await page.evaluate(async () => {
    const THREE = await import('/node_modules/.vite/deps/three.js')
    const { people, robot, renderer } = window.actorPreview
    const person = people[0].userData.actorLod.levels[0].object
    person.traverse(o=>{if(o.isSkinnedMesh)o.computeBoundingBox()})
    return { statuses:[...people,robot].map(root=>root.userData.assetModelStatus), bounds: new THREE.Box3().setFromObject(person).getSize(new THREE.Vector3()).toArray(), bones:people.map(root=>{let count=0;root.traverse(o=>{if(o.isBone)count++});return count}), calls:renderer.info.render.calls, triangles:renderer.info.render.triangles }
  })
  console.log(stats)
  assert.ok(stats.bounds[1] > 1.5 && stats.bounds[1] < 2, 'animated adult must remain human-sized')
  assert.ok(await page.evaluate(()=>{
    const roots=window.actorPreview.people
    const first=roots[0].userData.actorLod.levels[0].object.getObjectByName('Head')
    const second=roots[1].userData.actorLod.levels[0].object.getObjectByName('Head')
    return first && second && first !== second && first.parent !== second.parent
  }), 'each resident must own independent bones')
  await page.screenshot({path:output+'lineup.png'})
  await page.getByRole('button',{name:'暂停动作'}).click()
  const frozen = await page.evaluate(()=>window.actorPreview.people[0].userData.actorLod.levels[0].object.getObjectByName('UpperLegL')?.quaternion.toArray())
  await page.waitForTimeout(200)
  const after = await page.evaluate(()=>window.actorPreview.people[0].userData.actorLod.levels[0].object.getObjectByName('UpperLegL')?.quaternion.toArray())
  assert.ok(frozen && after && Math.abs(Math.abs(after.reduce((dot,v,i)=>dot+v*frozen[i],0))-1)<1e-6, 'paused pose must not change; q and -q represent the same orientation')
  await page.evaluate(()=>window.actorPreview.robotView())
  await page.waitForTimeout(100);await page.screenshot({path:output+'robot.png'})
  const fallback = await browser.newPage()
  await fallback.route('**/assets/actors/*.glb',route=>route.abort())
  await fallback.goto(url);await fallback.waitForFunction(()=>window.actorPreview?.ready)
  assert.deepEqual(await fallback.evaluate(()=>[...window.actorPreview.people,window.actorPreview.robot].map(root=>root.userData.assetModelStatus)),['fallback','fallback','fallback','fallback'])
  await fallback.close()
  await page.goto(url.replace('actors-preview','arena-preview'))
  await page.getByRole('button',{name:'机器人跟随',exact:true}).click()
  await page.waitForFunction(()=>document.querySelector('.twin-quality')?.title.startsWith('骨骼人物'))
  await page.waitForTimeout(1600)
  await page.screenshot({path:output+'arena-robot.png'})
  await page.getByRole('combobox',{name:'选择沙盘对象'}).selectOption('resident-04')
  await page.waitForTimeout(100)
  assert.equal(await page.getByText('模型核验居民',{exact:true}).count()>0,true)
  await page.evaluate(() => {
    Object.assign(window.arenaPreview.robot, { state:'executing', battery:38, task_queue:[{ id:'qa-route', label:'前往北侧集合点', status:'executing', progress:.42, ends_at_seconds:28, route_points:[] }] })
  })
  await page.getByRole('combobox',{name:'选择沙盘对象'}).selectOption('robot')
  assert.equal(await page.getByRole('button',{name:'到达目标后可广播'}).isDisabled(),true)
  assert.equal(await page.getByRole('progressbar',{name:'当前路线完成进度'}).getAttribute('value'),'42')
  await page.screenshot({path:output+'arena-execution-desktop.png'})
  await page.evaluate(() => { window.arenaPreview.robot.state='blocked'; window.arenaPreview.robot.task_queue[0].status='blocked' })
  await page.getByRole('button',{name:'重新规划当前路线'}).click()
  await page.evaluate(() => { window.arenaPreview.robot.state='arrived'; window.arenaPreview.robot.task_queue[0].status='completed' })
  await page.getByRole('button',{name:'在此执行疏散广播'}).click()
  assert.deepEqual(await page.evaluate(()=>window.arenaCommands),['replan','broadcast'])
  await page.setViewportSize({width:390,height:844})
  await page.getByRole('button',{name:'在此执行疏散广播'}).scrollIntoViewIfNeeded()
  assert.equal(await page.getByRole('navigation',{name:'空间直接操作工具'}).isVisible(),false,'mobile inspector replaces tool rack')
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'no horizontal overflow')
  await page.screenshot({path:output+'arena-execution-mobile.png'})
  await page.evaluate(() => { window.arenaPreview.robot=null })
  assert.equal(await page.locator('.robot-execution').count(),0)
  assert.deepEqual(errors,[])
  console.log('Model load, independent rigs, pause, fallback and execution-panel state/command checks passed. Captures:',output)
} finally { await browser.close() }
