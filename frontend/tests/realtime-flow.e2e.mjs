// Run against an isolated local API. QA_PASSWORD must be supplied explicitly.
import assert from 'node:assert/strict'
import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
const { default: playwright } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
assert.ok(process.env.QA_PASSWORD, 'Set QA_PASSWORD for the isolated review server')
const base = process.env.QA_BASE_URL || 'http://127.0.0.1:5173'
const apiRoot = process.env.QA_API_URL || 'http://127.0.0.1:8000/api/v1'
const artifacts = resolve(process.env.QA_ARTIFACT_DIR || '../output/playwright/realtime-upgrade')
mkdirSync(artifacts, { recursive: true })
const browser = await playwright.chromium.launch({ headless: true, ...(process.env.QA_BROWSER_PATH ? { executablePath: process.env.QA_BROWSER_PATH } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
const page = await context.newPage(), errors = [], checks = []
page.setDefaultTimeout(25000)
page.on('pageerror', e => errors.push(e.message))
let token, drillId, phone
const frames = []
function observe(p, name) { p.on('websocket', socket => socket.on('framereceived', frame => { try { frames.push({ client: name, ...JSON.parse(String(frame.payload)) }) } catch {} })) }
observe(page, 'director')
async function api(path, method = 'GET', data) {
  const response = await context.request.fetch(apiRoot + path, { method, headers: token ? { Authorization: 'Bearer ' + token } : {}, ...(data ? { data } : {}) })
  assert.ok(response.ok(), `${method} ${path}: ${response.status()} ${response.ok() ? '' : await response.text()}`)
  return response.json()
}
async function screenshot(name, target = page) { await target.screenshot({ path: resolve(artifacts, name + '.png'), fullPage: true }) }
async function noOverflow(target) { assert.ok(await target.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Horizontal overflow') }
async function confirm(kind) {
  for(let attempt=0;attempt<3;attempt++) {
    const response=page.waitForResponse(r=>r.url().endsWith('/commands')&&r.request().postDataJSON()?.kind===kind)
    await page.getByRole('button',{name:'确认执行',exact:true}).click()
    const result=await response
    if(result.ok()) return
    assert.equal(result.status(),409,await result.text())
    await page.getByText(/现场.*变化|重新.*预演|重新.*预览/).first().waitFor()
  }
  throw new Error('Preview remains stale after three explicit confirmations')
}
try {
  token = (await api('/auth/login', 'POST', { username: 'admin', password: process.env.QA_PASSWORD })).access_token
  const demo = await api('/communities/demo-ready', 'POST')
  drillId = (await api('/scenes/' + demo.scene_id + '/drills', 'POST', { name: '实时联动专项验收', time_scale: 1 })).id
  await page.goto(base + '/login')
  // Session cookie from context.request is restored by the real application.
  await page.waitForURL('**/projects')
  await page.getByRole('button', { name: '三维预览', exact: true }).click()
  await page.locator('.atlas-case__visual canvas').waitFor()
  await screenshot('home-live-preview'); await noOverflow(page)
  checks.push('Home switches to the actual configured Three.js world')
  await page.goto(`${base}/communities/${demo.community.id}/operations?scene=${demo.scene_id}&drill=${drillId}`)
  await page.getByRole('button', { name: '开始推演', exact: true }).click()
  await page.locator('.sync-indicator').filter({ hasText: '实时同步' }).waitFor()
  // Await the actual alarm transition before previewing; its events legitimately
  // invalidate an earlier version and require a second human confirmation.
  for (let attempt=0; attempt<60; attempt++) {
    const state=await api('/drills/'+drillId)
    if(state.events.some(event=>event.event_type==='robot.alarm_confirmed')) break
    if(attempt===59) throw new Error('Patrol never confirmed the fire')
    await page.waitForTimeout(500)
  }
  const phoneContext = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })
  await phoneContext.addInitScript(() => {
    window.__qaSockets = []
    const NativeSocket = window.WebSocket
    window.WebSocket = class extends NativeSocket {
      constructor(...args) { super(...args); window.__qaSockets.push(this) }
    }
  })
  phone = await phoneContext.newPage(); phone.setDefaultTimeout(25000); phone.on('pageerror', e => errors.push(e.message)); observe(phone, 'phone')
  const invite = await api('/drills/' + drillId + '/participant-invite', 'POST')
  await phone.goto(`${base}/participant/${drillId}?code=${invite.code}`)
  await phone.locator('#participant-name').fill('联动验收组')
  await phone.getByRole('button', { name: '登记并接收任务', exact: true }).click()
  await page.locator('.atlas-director-modes').getByRole('button', { name: '指挥', exact: true }).click()
  await page.locator('.twin-object-nav select').selectOption('resident-1')
  await page.getByRole('button', { name: '指挥此居民', exact: true }).click()
  await page.getByRole('button', { name: '向北门分流', exact: true }).click()
  await confirm('residents.assign')
  await page.locator('.execution-link').click()
  await page.locator('.execution-feedback').getByRole('heading', {name:/指挥.*居民|居民.*分流/}).first().waitFor()
  await screenshot('execution-desktop'); await noOverflow(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await screenshot('execution-mobile'); await noOverflow(page)
  await page.setViewportSize({ width: 1440, height: 960 })
  await page.locator('.director-drawer').getByRole('button', { name: /关闭/ }).click()
  await page.locator('.twin-object-nav select').selectOption({ label: '北门主通道（畅通）' })
  await page.getByRole('button', { name: '在此注入事件', exact: true }).click()
  await confirm('event.inject')
  // Confirmation dismisses the selection panel. Verify the authoritative
  // road and its delivery to the phone, rather than an obsolete panel state.
  assert.ok((await api('/drills/'+drillId)).simulation.road_network.edges.some(edge=>edge.name==='北门主通道'&&edge.status==='blocked'))
  await phone.getByText(/导演注入|通道堵塞|北门主通道/).first().waitFor()
  const result = await api('/drills/' + drillId)
  assert.ok(result.commands.some(c => c.kind === 'residents.assign'))
  assert.ok(result.commands.some(c => c.kind === 'event.inject' && c.status === 'completed'))
  assert.ok(frames.some(f => f.client === 'phone' && f.type === 'drill.delta'))
  assert.ok(frames.some(f => f.client === 'director' && f.type === 'drill.delta'))
  checks.push('UI resident command, execution receipt, real road closure and delta delivery to both clients')
  await screenshot('phone-linked', phone); await noOverflow(phone)
  const snapshotsBefore = frames.filter(f => f.client === 'phone' && f.type === 'drill.snapshot').length
  await phoneContext.setOffline(true)
  await phone.evaluate(() => window.__qaSockets.forEach(socket => socket.close(4000, 'test disconnect')))
  await phone.locator('.participant-header i[data-live="false"]').waitFor()
  await phoneContext.setOffline(false)
  await phone.locator('.participant-header i[data-live="true"]').waitFor({ timeout: 30000 })
  assert.ok(frames.filter(f => f.client === 'phone' && f.type === 'drill.snapshot').length > snapshotsBefore)
  assert.equal(await phone.locator('#participant-name').count(), 0)
  checks.push('Phone reconnect retains its participant identity')
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ checks, errors, drillId, artifacts, directorDeltas: frames.filter(f => f.client === 'director' && f.type === 'drill.delta').length, phoneDeltas: frames.filter(f => f.client === 'phone' && f.type === 'drill.delta').length }, null, 2))
} catch (error) {
  await screenshot('failure').catch(() => {}); if (phone) await screenshot('phone-failure', phone).catch(() => {})
  throw error
} finally {
  if (drillId && token) { const state = await api('/drills/' + drillId).catch(() => null); if (state?.status === 'running') await api('/drills/' + drillId + '/state', 'PATCH', { action: 'pause' }).catch(() => {}) }
  await browser.close()
}
