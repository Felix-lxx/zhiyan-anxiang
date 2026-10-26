// Bounded UI check with production components; no accounts or live drills are modified.
import assert from 'node:assert/strict'
import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
const { default: playwright } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await playwright.chromium.launch({ headless: true, ...(process.env.QA_BROWSER_PATH ? { executablePath: process.env.QA_BROWSER_PATH } : {}) })
const output = resolve('../output/playwright/director-overlays')
mkdirSync(output, { recursive: true })
const overlap = (a, b) => Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x) > 1 && Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y) > 1
try {
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/__layout_api__/**', route => route.fulfill({ json: { configured: false, model: null } }))
  await page.goto((process.env.QA_BASE_URL || 'http://127.0.0.1:5173') + '/tests/arena-recovery.html?rescue=1')
  await page.locator('canvas').first().waitFor({ timeout: 30000 })
  for (const [width, height] of [[1440, 900], [1024, 720], [768, 800], [390, 844]]) {
    await page.setViewportSize({ width, height })
    await page.evaluate(() => window.arenaQA.coach(true))
    const coach = page.getByRole('complementary', { name: '引导演练', exact: true })
    await coach.getByRole('button', { name: '收起引导演练' }).waitFor()
    // Let ResizeObserver finish its frame after the viewport/toolbar changes.
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    const panel = await coach.boundingBox()
    assert.ok(panel.width > 250 && panel.height > 230, `${width}: useful panel size`)
    assert.ok(panel.x >= 0 && panel.x + panel.width <= width + 1)
    for (const selector of ['.scene-utilities', '.atlas-director-modes', '.director-topbar', '.director-rail', '.exercise-timeline']) {
      const box = await page.locator(selector).boundingBox()
      assert.ok(box && !overlap(panel, box), `${width}: coach overlaps ${selector}`)
    }
    assert.ok(await coach.evaluate(el => el.scrollWidth <= el.clientWidth + 1), 'No horizontal coach overflow')
    const body = coach.getByLabel('引导演练内容')
    await body.evaluate(el => { el.scrollTop = el.scrollHeight })
    await coach.getByRole('button', { name: '收起引导演练' }).click()
    assert.equal(await coach.count(), 0, 'Close remains reachable after scrolling')
    await page.getByRole('button', { name: '当前训练任务', exact: true }).click()
    await coach.getByRole('button', { name: '检查任务与遗漏' }).click()
    assert.equal(await coach.isVisible(), false, 'Task drawer replaces the coach')
    await page.getByRole('button', { name: '关闭面板' }).click()
    assert.equal(await coach.isVisible(), true, 'Closing the task drawer restores the coach')
    await coach.getByText('本场已结束，结果已冻结', { exact: true }).scrollIntoViewIfNeeded()
    assert.equal(await coach.getByText('现场持续推演中', { exact: true }).count(), 0)
    await body.evaluate(el => { el.scrollTop = 0 })
    await page.screenshot({ path: resolve(output, `coach-${width}.png`) })
    await page.evaluate(() => window.arenaQA.preview(true))
    const preview = page.locator('.spatial-action-preview')
    await preview.waitFor()
    assert.equal(await coach.isVisible(), false, 'Preview does not stack over the coach')
    const previewBox = await preview.boundingBox()
    for (const selector of ['.scene-utilities', '.atlas-director-modes']) {
      assert.ok(!overlap(previewBox, await page.locator(selector).boundingBox()), `${width}: preview avoids ${selector}`)
    }
    await page.screenshot({ path: resolve(output, `preview-${width}.png`) })
    await page.evaluate(() => window.arenaQA.assistant(true))
    const assistant = page.getByLabel('场景 AI 助手', { exact: true })
    await assistant.waitFor()
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    assert.equal(await coach.isVisible(), false)
    const assistantBox = await assistant.boundingBox()
    assert.ok(assistantBox.x >= 0 && assistantBox.x + assistantBox.width <= width + 1)
    assert.ok(await assistant.evaluate(el => el.scrollWidth <= el.clientWidth + 1))
    if (width > 760) assert.ok(!overlap(assistantBox, await page.locator('.scene-utilities').boundingBox()), 'Assistant avoids scene utilities')
    else assert.equal(await page.locator('.director-stage').getAttribute('inert'), '', 'Mobile assistant isolates scene focus')
    await page.screenshot({ path: resolve(output, `assistant-${width}.png`) })
    await assistant.getByRole('button', { name: '关闭 AI 助手' }).click()
  }
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ checks: ['引导、预览避让工具栏与模式栏', '收起入口不随内容滚走', '引导与任务/预览/助手互斥', '助手桌面分栏/手机焦点隔离', '结束态文案正确', '1440/1024/768/390 布局'], errors, output }, null, 2))
} finally { await browser.close() }
