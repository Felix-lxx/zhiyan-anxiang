// Run only against an isolated QA database: this creates one ready (not started) run.
import assert from 'node:assert/strict'
const { default: playwright } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
assert.ok(process.env.QA_PASSWORD, 'QA_PASSWORD is required')
const base = process.env.QA_BASE_URL || 'http://127.0.0.1:5189'
const api = process.env.QA_API_URL || 'http://127.0.0.1:8019/api/v1'
const browser = await playwright.chromium.launch({ headless: true, ...(process.env.QA_BROWSER_PATH ? { executablePath: process.env.QA_BROWSER_PATH } : {}) })
let context
try {
  context = await browser.newContext()
  const login = await context.request.post(api + '/auth/login', { data: { username: process.env.QA_USERNAME || 'admin', password: process.env.QA_PASSWORD } })
  assert.ok(login.ok())
  const headers = { Authorization: 'Bearer ' + (await login.json()).access_token }
  async function read(path) {
    const response = await context.request.get(api + path, { headers })
    assert.ok(response.ok(), `${path}: ${response.status()}`)
    return response.json()
  }
  const page = await context.newPage()
  await page.goto(base + '/projects')
  const home = page.locator('.training-home')
  await home.getByText(/进度读取至/).waitFor({ timeout: 30000 })
  await home.getByRole('button', { name: /恢复现场与当前任务|核对简报并进入/ }).click()
  await page.locator('.training-journey').waitFor({ timeout: 60000 })
  const resumed = new URL(page.url())
  const originalId = resumed.searchParams.get('drill')
  const sceneId = resumed.searchParams.get('scene')
  assert.ok(originalId && sceneId)
  const before = await read(`/scenes/${sceneId}/drills?summary=true`)
  await page.reload()
  await page.locator('.training-journey').waitFor({ timeout: 60000 })
  assert.equal(new URL(page.url()).searchParams.get('drill'), originalId)
  assert.equal((await read(`/scenes/${sceneId}/drills?summary=true`)).length, before.length)
  await page.goto(base + '/projects')
  await page.getByLabel('更换场景', { exact: true }).selectOption(sceneId)
  await page.locator('.atlas-case__enter').click()
  await page.getByRole('heading', { name: '训练简报', exact: true }).waitFor({ timeout: 60000 })
  const createdId = new URL(page.url()).searchParams.get('drill')
  assert.ok(createdId && createdId !== originalId, 'Case entry creates a distinct run')
  assert.equal(new URL(page.url()).searchParams.has('new'), false, 'Creation flag consumed')
  assert.equal((await read(`/drills/${createdId}`)).status, 'ready')
  await page.reload()
  await page.locator('.training-journey').waitFor({ timeout: 60000 })
  assert.equal(new URL(page.url()).searchParams.get('drill'), createdId)
  assert.equal((await read(`/scenes/${sceneId}/drills?summary=true`)).length, before.length + 1)
  console.log(JSON.stringify({ checks: ['resume existing run', 'refresh preserves identity', 'new case creates one ready run', 'refresh does not repeat creation'] }))
} finally {
  if (context) {
    await context.request.dispose()
    await context.close()
  }
  await browser.close()
}
