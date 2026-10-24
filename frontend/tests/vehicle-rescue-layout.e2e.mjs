// Isolated layout smoke check: no real drills or accounts are changed.
import assert from 'node:assert/strict'
import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
const { default: playwright } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await playwright.chromium.launch({ headless: true, ...(process.env.QA_BROWSER_PATH ? { executablePath: process.env.QA_BROWSER_PATH } : {}) })
const output = resolve('../output/playwright/vehicle-rescue')
mkdirSync(output, { recursive: true })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto((process.env.QA_BASE_URL || 'http://127.0.0.1:5173') + '/tests/arena-recovery.html?rescue=1')
  await page.locator('canvas').first().waitFor({ timeout: 30000 })
  for (const mode of ['spray', 'load']) {
    await page.evaluate(mode => { window.arenaQA.rescue(mode); window.arenaQA.vehicles(false) }, mode)
    await page.getByRole('group', { name: '现场显示与车辆工具' }).getByRole('button', { name: '车辆调度' }).click()
    for (const [width, height] of [[1440, 900], [1366, 650], [1024, 768], [390, 844]]) {
      await page.setViewportSize({ width, height })
      const panel = page.locator('.vehicle-dispatch')
      await panel.getByRole('heading', { name: '车辆调度与到场处置' }).waitFor()
      const utilities = page.getByRole('group', { name: '现场显示与车辆工具' })
      if (!await utilities.getByLabel('三维画质').count()) await utilities.getByRole('button', { name: '画面设置', exact: true }).click()
      await utilities.getByLabel('三维画质').selectOption('medium')
      const cutaway = utilities.getByRole('button', { name: /查看楼内透视|恢复建筑外观/ })
      const pressed = await cutaway.getAttribute('aria-pressed')
      await cutaway.click()
      assert.notEqual(await cutaway.getAttribute('aria-pressed'), pressed)
      const toolbar = await utilities.boundingBox(), drawer = await page.locator('.director-drawer').boundingBox()
      assert.ok(toolbar.x >= 0 && toolbar.x + toolbar.width <= width + 1)
      assert.ok(toolbar.y + toolbar.height <= drawer.y + 1, 'Persistent utilities do not cover the drawer')
      await panel.locator('.vehicle-dispatch__service').scrollIntoViewIfNeeded()
      const bounds = await panel.boundingBox()
      assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= width + 1, 'Panel stays inside viewport')
      assert.ok(await panel.evaluate(el => el.scrollWidth <= el.clientWidth + 1), 'No horizontal overflow')
      const overlap = await panel.locator('button').evaluateAll(buttons => buttons.some((button, index) => buttons.slice(index + 1).some(other => {
        const a = button.getBoundingClientRect(), b = other.getBoundingClientRect()
        return a.width && b.width && Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1 && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1
      })))
      assert.equal(overlap, false, 'Action buttons do not overlap')
      if (mode === 'spray') await panel.getByRole('button', { name: '停止喷水' }).scrollIntoViewIfNeeded()
      await page.screenshot({ path: resolve(output, `${mode}-${width}.png`) })
    }
    await page.evaluate(() => window.arenaQA.vehicles(false))
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.evaluate(() => window.arenaQA.rescueFocus())
    await page.waitForTimeout(1000) // Allow the existing camera easing to settle for the screenshot.
    await page.screenshot({ path: resolve(output, `${mode}-scene.png`) })
  }
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ checks: ['喷水 / 担架模型加载无脚本异常', '1440×900 / 1366×650 / 1024×768 / 390×844 抽屉无横向溢出', '画质和楼内透视在任务抽屉打开时可操作且无重叠'], errors, output }, null, 2))
} finally { await browser.close() }
