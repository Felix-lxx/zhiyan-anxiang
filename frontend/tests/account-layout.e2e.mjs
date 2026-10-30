// Uses disposable QA services; writes profile settings and creates demonstration data.
import assert from 'node:assert/strict'
import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
const { default: playwright } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
assert.ok(process.env.QA_PASSWORD, 'QA_PASSWORD is required')
const base = process.env.QA_BASE_URL || 'http://127.0.0.1:5173'
const apiRoot = process.env.QA_API_URL || 'http://127.0.0.1:8000/api/v1'
const artifacts = resolve('../output/playwright/account-layout')
mkdirSync(artifacts, { recursive: true })
const browser = await playwright.chromium.launch({ headless: true, ...(process.env.QA_BROWSER_PATH ? { executablePath: process.env.QA_BROWSER_PATH } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage(), errors = [], checks = []
page.setDefaultTimeout(20000)
page.on('pageerror', e => errors.push(e.message))
let token, initial
async function api(path, method = 'GET', data) {
  const r = await context.request.fetch(apiRoot + path, { method, headers: token ? { Authorization: 'Bearer ' + token } : {}, ...(data ? { data } : {}) })
  assert.ok(r.ok(), `${path}: ${r.status()} ${r.ok() ? '' : await r.text()}`)
  return r.json()
}
async function inspect(name, widths = [1440, 1024, 390]) {
  for (const width of widths) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 })
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    if (name === 'replay') {
      assert.equal(await page.locator('.atlas-replay__world>nav').evaluate(e => getComputedStyle(e).position), 'static')
      const world = await page.locator('.atlas-replay__world').boundingBox()
      assert.ok(world.width >= (width === 390 ? 340 : 460), 'Replay world must not be squeezed into a narrow middle column')
    }
    await page.screenshot({ path: resolve(artifacts, `${name}-${width}.png`), fullPage: true })
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${name} overflows at ${width}`)
  }
  await page.setViewportSize({ width: 1440, height: 1000 })
}
try {
  token = (await api('/auth/login', 'POST', { username: 'admin', password: process.env.QA_PASSWORD })).access_token
  const demo = await api('/communities/demo-ready', 'POST')
  initial = await api('/account/profile')
  await api('/account/profile', 'PATCH', { display_name: '页面验收员', organization: '', text_size: 'comfortable', reduced_motion: false, default_community_id: null, revision: initial.revision })
  await page.goto(base + '/login')
  // API login already set the HttpOnly cookie on this browser context.
  await page.waitForURL('**/projects')
  await page.getByRole('button', { name: '打开个人中心', exact: true }).click()
  await page.locator('#profile-name').fill('安巷社区演练负责人')
  await page.locator('#profile-organization').fill('安巷社区物业服务中心')
  await page.getByRole('button', { name: '阅读与操作偏好', exact: true }).click()
  await page.locator('#profile-community').selectOption(demo.community.id)
  await page.getByLabel('大字 · 正文 18 像素', { exact: true }).check()
  await page.getByLabel('减少界面动画', { exact: false }).check()
  await page.route('**/account/profile', route => route.request().method() === 'PATCH' ? route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: '测试：服务暂不可用，请重试。' }) }) : route.continue())
  await page.getByRole('button', { name: '保存设置', exact: true }).click()
  await page.getByRole('alert').filter({ hasText: '测试：服务暂不可用' }).waitFor()
  assert.equal(await page.locator('#profile-name').inputValue(), '安巷社区演练负责人')
  assert.equal((await api('/account/profile')).display_name, '页面验收员')
  await page.unroute('**/account/profile')
  await page.getByRole('button', { name: '保存设置', exact: true }).click()
  await page.getByText('资料与阅读设置已保存，刷新或再次登录后仍然生效。', { exact: true }).waitFor()
  await page.reload(); await page.locator('#profile-community').waitFor()
  assert.equal(await page.locator('#profile-name').inputValue(), '安巷社区演练负责人')
  assert.equal(await page.locator('#profile-community').inputValue(), demo.community.id)
  assert.equal(await page.locator('html').getAttribute('data-reading-size'), 'large')
  assert.ok(await page.locator('.account-heading p').evaluate(e => parseFloat(getComputedStyle(e).fontSize) >= 18))
  await inspect('account')
  await page.getByRole('button', { name: '登录与安全', exact: true }).click()
  await inspect('account-security', [1440, 390])
  await page.getByRole('button', { name: '个人资料', exact: true }).click()
  checks.push('Profile saves to API, refresh restores preferences, failed save retains input without false persistence')
  await page.locator('#profile-organization').fill('未保存修改')
  page.once('dialog', dialog => dialog.dismiss())
  await page.getByRole('button', { name: '演练首页', exact: true }).click()
  assert.ok(page.url().includes('section=account'))
  await page.getByRole('button', { name: '撤销修改', exact: true }).click()
  await page.getByRole('button', { name: '演练首页', exact: true }).click()
  await page.locator('.atlas-case__details h2').waitFor(); await inspect('home')
  await page.getByRole('button', { name: '复盘记录', exact: true }).click()
  await page.getByLabel('搜索演练', { exact: true }).fill('不存在的场次')
  await page.getByText('没有匹配的记录，请调整搜索词或状态。', { exact: true }).waitFor()
  await page.getByRole('button', { name: '清除筛选', exact: true }).click()
  await inspect('history', [1440, 390])
  checks.push('Unsaved-navigation protection and actual history filtering')
  await page.goto(base + `/communities/${demo.community.id}/scenes?scene=${demo.scene_id}`)
  await page.locator('.scene-live-preview canvas').first().waitFor(); await inspect('scene')
  await page.goto(base + `/communities/${demo.community.id}/operations?scene=${demo.scene_id}&drill=${demo.drill_id}&mode=replay`)
  await page.locator('.atlas-replay').waitFor(); await inspect('replay')
  await page.goto(base + '/projects?section=communities'); await page.locator('.home-project-row').first().waitFor(); await inspect('communities', [1440, 390])
  await page.goto(base + '/projects?section=guide'); await page.locator('.home-guide-page').waitFor(); await inspect('guide', [1440, 390])
  checks.push('Home, account, history, scene, replay, community and guide layout at desktop/tablet/mobile widths')
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ checks, errors, artifacts }, null, 2))
} catch (error) {
  await page.screenshot({ path: resolve(artifacts, 'failure.png'), fullPage: true }).catch(() => {})
  throw error
} finally {
  if (initial && token) {
    const current = await api('/account/profile')
    const { display_name, organization, text_size, reduced_motion, default_community_id } = initial
    await api('/account/profile', 'PATCH', { display_name, organization, text_size, reduced_motion, default_community_id, revision: current.revision })
  }
  await browser.close()
}
