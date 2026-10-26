// Real API + real browser on an isolated QA database. No mocked successful commands.
import assert from 'node:assert/strict'
import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
const { default: playwright } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
assert.ok(process.env.QA_PASSWORD, 'QA_PASSWORD is required')
const base = process.env.QA_BASE_URL || 'http://127.0.0.1:5189'
const api = process.env.QA_API_URL || 'http://127.0.0.1:8019/api/v1'
const output = resolve('../output/playwright/training-journey')
mkdirSync(output, { recursive: true })
const browser = await playwright.chromium.launch({ headless: true, ...(process.env.QA_BROWSER_PATH ? { executablePath: process.env.QA_BROWSER_PATH } : {}) })
const errors = []
let page
let cleanup
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const login = await context.request.post(api + '/auth/login', { data: { username: process.env.QA_USERNAME || 'admin', password: process.env.QA_PASSWORD } })
  assert.ok(login.ok(), 'QA login')
  const headers = { Authorization: 'Bearer ' + (await login.json()).access_token }
  async function call(method, path, data) {
    const response = await context.request.fetch(api + path, { method, headers, ...(data ? { data } : {}) })
    assert.ok(response.ok(), `${method} ${path}: ${response.status()}`)
    return response.json()
  }
  const community = await call('POST', '/communities/demo')
  const templates = await call('GET', '/scene-templates')
  const scene = await call('POST', `/communities/${community.id}/scenes`, {
    template_id: templates.find(t => t.code === 'kitchen_fire').id, name: '厨房训练工作流',
  })
  const sceneRoot = `/scenes/${scene.id}`
  const sources = await call('GET', sceneRoot + '/fire-sources')
  await call('PATCH', sceneRoot + '/parameters', {
    fire_source_type: 'kitchen', fire_source_object_id: sources[0].id, fire_floor: 2, fire_room: 'east', room_door_state: 'closed',
    start_time: '18:30', wind_direction: '微风', resident_count: 8, hydrant_status: 'available', south_lane_status: 'open', stair_width: 1.2,
  })
  await call('POST', sceneRoot + '/publish')
  const created = await call('POST', sceneRoot + '/drills', { name: '厨房训练 · 工作区验收', training_mode: 'teaching' })
  cleanup = async () => {
    const latest = await call('GET', '/drills/' + created.id)
    if (latest.status === 'running') await call('PATCH', '/drills/' + created.id + '/state', { action: 'pause' })
  }
  const url = `${base}/communities/${community.id}/operations?scene=${scene.id}&drill=${created.id}`
  page = await context.newPage()
  page.on('pageerror', error => errors.push(error.message))
  await page.goto(url)
  await page.getByRole('heading', { name: '训练简报', exact: true }).waitFor({ timeout: 60000 })
  const panel = page.locator('.training-journey')
  assert.ok(await panel.getByText('8 人，含 2 名重点人员', { exact: true }).isVisible())
  for (const [width, height] of [[1440, 900], [1366, 650], [1024, 768], [768, 800], [390, 844], [360, 780]]) {
    await page.setViewportSize({ width, height })
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    const drawer = page.locator('.director-drawer')
    const a = await drawer.boundingBox(), top = await page.locator('.director-topbar').boundingBox()
    assert.ok(a.y >= top.y + top.height - 1, `${width}: work area avoids persistent controls`)
    assert.ok(a.x >= 0 && a.x + a.width <= width + 1 && a.y + a.height <= height + 1, `${width}: drawer bounds`)
    assert.ok(await panel.evaluate(el => el.scrollWidth <= el.clientWidth + 1), `${width}: no horizontal overflow`)
    assert.ok(await panel.evaluate(el => el.clientHeight > 180 && el.scrollHeight > el.clientHeight), `${width}: independently scrollable briefing`)
    if (width > 1100) {
      const stage = await page.locator('.director-stage').boundingBox()
      assert.ok(stage.x + stage.width <= a.x + 1, '3D canvas reserves real space')
    }
    await panel.evaluate(el => { el.scrollTop = 0 })
    await page.screenshot({ path: resolve(output, `briefing-${width}.png`) })
  }
  await page.setViewportSize({ width: 1440, height: 900 })
  await panel.getByRole('button', { name: /^开始训练/ }).click()
  await page.getByRole('heading', { name: '当前训练任务', exact: true }).waitFor()
  // Await the actual background scheduler and authoritative alarm event.
  await panel.getByRole('button', { name: /^确认报警并组织响应/ }).waitFor({ timeout: 90000 })
  await panel.getByRole('button', { name: /^确认报警并组织响应/ }).click()
  await page.waitForFunction(() => !document.querySelector('.training-journey')?.textContent.includes('确认报警并组织响应'))
  const acknowledged = await call('GET', '/drills/' + created.id)
  assert.ok(acknowledged.events.some(e => e.event_type === 'participant.acknowledge'), 'Response confirmation persists')
  await page.getByRole('button', { name: '暂停演练', exact: true }).click()
  await panel.getByText(/时钟已暂停/).waitFor()
  await page.reload()
  await page.getByRole('heading', { name: '当前训练任务', exact: true }).waitFor({ timeout: 60000 })
  await panel.getByText(/时钟已暂停/).waitFor()
  await panel.getByRole('button', { name: /^安排分流与重点护送/ }).click()
  const assistant = page.getByLabel('场景 AI 助手', { exact: true })
  await assistant.waitFor()
  assert.equal(await page.locator('.director-drawer:visible').count(), 0, 'Assistant replaces task workspace')
  assert.ok(await assistant.getByRole('button', { name: '目标计划', exact: true }).getAttribute('aria-pressed') === 'true')
  for (const [width, height] of [[1366, 650], [390, 844]]) {
    await page.setViewportSize({ width, height })
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    assert.ok(await assistant.evaluate(el => el.scrollWidth <= el.clientWidth + 1))
    await page.screenshot({ path: resolve(output, `assistant-${width}.png`) })
  }
  await assistant.getByRole('button', { name: '返回当前任务', exact: true }).click()
  await panel.waitFor()
  await page.setViewportSize({ width: 1440, height: 900 })
  const task = created.tasks.find(t => t.kind === 'gas_off')
  await panel.getByText('本次训练简报', { exact: true }).click()
  await panel.locator('.training-journey__responsibilities').getByRole('button', { name: new RegExp(task.title) }).click()
  const workflow = page.locator('.task-workflow')
  await workflow.waitFor()
  assert.equal(await workflow.count(), 1, 'Task navigation focuses one concrete task')
  await page.getByRole('button', { name: '继续演练', exact: true }).click()
  await workflow.getByRole('button', { name: '总控代办此任务', exact: true }).click()
  await workflow.getByRole('button', { name: '回执已到达目标', exact: true }).click()
  const evidence = workflow.getByRole('textbox')
  await evidence.fill('隔离验收：核对燃气阀门并记录关闭处置结果')
  await page.getByRole('button', { name: '返回当前任务', exact: true }).click()
  await panel.getByRole('button', { name: /^提交核验：/ }).waitFor({ timeout: 20000 })
  await panel.getByRole('button', { name: /^提交核验：/ }).click()
  assert.equal(await evidence.inputValue(), '隔离验收：核对燃气阀门并记录关闭处置结果', 'Switching work areas preserves evidence draft')
  await workflow.getByRole('button', { name: '提交核验证据', exact: true }).click()
  await workflow.getByText(/^结果证据：/).waitFor()
  const saved = await call('GET', '/drills/' + created.id)
  assert.equal(saved.tasks.find(t => t.id === task.id).status, 'completed')
  assert.ok(saved.events.some(e => e.event_type === 'task.completed' && e.payload.task_id === task.id))
  await call('PATCH', '/drills/' + created.id + '/state', { action: 'pause' })
  await page.goto(base + '/projects')
  await page.locator('.training-home').waitFor()
  await page.locator('.training-home').getByText(/进度读取至/).waitFor({ timeout: 30000 })
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 })
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1))
    await page.screenshot({ path: resolve(output, `home-${width}.png`), fullPage: true })
  }
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ checks: ['6 responsive viewports', 'frozen briefing', 'real clock/alarm/acknowledgement', 'refresh recovery', 'assistant/task exclusivity', 'evidence draft retained and persisted', 'home resume'], output }, null, 2))
} catch (error) {
  if (page) { await page.screenshot({ path: resolve(output, 'failure.png'), fullPage: true }); console.error('Page:', page.url()); console.error((await page.locator('body').innerText()).slice(0, 5000)) }
  throw error
} finally { if (cleanup) await cleanup().catch(error => console.error('QA cleanup:', error.message)); await browser.close() }
