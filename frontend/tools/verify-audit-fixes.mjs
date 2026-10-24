// Local visual verification of the real workspace; no exercise commands are sent.
import assert from 'node:assert/strict'
import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const output = resolve('../output/playwright/audit-fixes-20261024')
mkdirSync(output, { recursive: true })
const browser = await chromium.launch({ headless: true, channel: 'msedge' })
const page = await browser.newPage({ viewport: { width: 1366, height: 650 } })
const faults = []
page.on('pageerror', error => faults.push(error.message))
const base = process.env.QA_BASE_URL || 'http://127.0.0.1:5173'
try {
  await page.goto(base + '/login?redirect=/projects')
  await page.getByRole('textbox', { name: '密码', exact: true }).fill(process.env.AUDIT_PASSWORD || 'Zhiyan@2026')
  await page.getByRole('button', { name: '进入工作台', exact: true }).click()
  await page.waitForURL('**/projects')
  const filter = page.getByRole('checkbox', { name: '显示验收场景与试验记录' })
  await filter.waitFor()
  await page.getByRole('combobox', { name: '更换场景' }).waitFor()
  const normalOptions = await page.getByRole('combobox', { name: '更换场景' }).locator('option').allTextContents()
  assert.ok(normalOptions.every(name => !/实跑验收|UI 自动验收|流程验收|图册交互验收/.test(name)))
  await filter.check()
  await page.getByRole('button', { name: '继续这场演练', exact: true }).waitFor()
  await page.getByRole('button', { name: '继续这场演练', exact: true }).click()
  await page.getByRole('button', { name: '打开安巷指挥助手' }).waitFor()
  await page.getByRole('button', { name: '打开安巷指挥助手' }).click()
  await page.getByRole('heading', { name: '疏散协同智能体' }).waitFor()
  for (const [width, height] of [[1366, 650], [390, 844]]) {
    await page.setViewportSize({ width, height })
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    const layout = await page.evaluate(() => {
      const header = document.querySelector('.director-topbar')
      const panel = document.querySelector('.scene-assistant')
      const h = header.getBoundingClientRect(), p = panel.getBoundingClientRect()
      return { header: { top: h.top, bottom: h.bottom }, panel: { top: p.top, bottom: p.bottom },
        headerVisible: getComputedStyle(header).visibility !== 'hidden',
        overflow: document.documentElement.scrollWidth > innerWidth }
    })
    assert.ok(layout.headerVisible && layout.header.top >= 0 && layout.header.bottom <= height, JSON.stringify(layout))
    assert.ok(layout.panel.top >= layout.header.bottom && layout.panel.bottom <= height + 1, JSON.stringify(layout))
    assert.equal(layout.overflow, false)
    if (width < 761) {
      await page.locator('.scene-assistant__run-controls').getByRole('button', { name: '继续演练' }).waitFor()
      assert.equal(await page.locator('.scene-assistant__run-controls button').first().isEnabled(), true)
    }
    await page.screenshot({ path: resolve(output, `assistant-${width}.png`) })
    console.log(JSON.stringify({ width, height, layout }))
  }
  assert.deepEqual(faults, [])
  console.log(JSON.stringify({ normalOptions, faults, output }))
} finally {
  await browser.close()
}
