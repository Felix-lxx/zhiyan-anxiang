// Isolated UI check: real production Vue/Three.js picking; no user DB mutations.
import assert from 'node:assert/strict'
import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { PerspectiveCamera, Vector3 } from '../node_modules/three/build/three.module.js'
const { default: playwright } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await playwright.chromium.launch({ headless: true, ...(process.env.QA_BROWSER_PATH ? { executablePath: process.env.QA_BROWSER_PATH } : {}) })
const output = resolve('../output/playwright/fire-source-selection'); mkdirSync(output, { recursive: true })
const capabilities = { code: 'night_charging_shed_fire', contract_version: 1, title: '夜间充电棚火灾', status: 'available', notice: '配置火点后预览并发布。', source_types: ['charging_shed'], location_kinds: ['object'], features: [], can_create: true, can_configure: true, can_preview: true, can_publish: true, can_run: true }
const sources = [
  { id: 'east', name: '东侧充电棚', object_type: 'charging_shed', x: 30, y: 35 },
  { id: 'west', name: '西侧备用充电棚', object_type: 'charging_shed', x: 70, y: 65 },
]
const initial = { fire_source_object_id: 'east', fire_source_type: 'charging_shed', start_time: '20:15', wind_direction: '微风', resident_count: 10, hydrant_status: 'available', south_lane_status: 'open', stair_width: 1.2 }
const preview = parameters => {
  const source = sources.find(item => item.id === parameters.fire_source_object_id)
  return { minute: 0, fire_level: '初起', smoke_level: '轻微', risk_level: '关注', route_advice: `巡检与断电目标：${source.name}`, explanation: '隔离场景用于三维选点与布局验证。', affected_targets: [source.name], simulation: {
    world: { parameters, fire_source: { location: { object_id: source.id } }, fire_origin: { x: source.x, y: source.y }, objects: sources.map(item => ({ ...item, type: item.object_type, width: 10, depth: 6, floors: 1, entry: { x: item.x, y: item.y + 6 } })) },
    spatial_network: { nodes: [], edges: [], stair_width: 1.2 }, road_network: { nodes: [], edges: [] },
    residents: [], helpers: [], vehicles: [], fire: { intensity: 18, smoke_radius: 4, temperature: 70 },
    environment: { east_hydrant: 'available', south_lane: 'open', visibility: 90 }, sensors: { temperature: 70, smoke_ppm: 50, alarm: true }, summary: { total: 10, evacuated: 0, missing: 0 },
  } }
}
try {
  const page = await browser.newPage(); const errors = []; page.on('pageerror', error => errors.push(error.message))
  let saved = { ...initial }, reads = 0, writes = 0, failSave = false
  const scene = () => ({ id: 'select-source', name: '双充电棚火点配置', status: 'draft', capabilities, versions: [{ version_number: 1, parameters: saved }] })
  await page.route('**/__scenario_layout__/**', route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (path.endsWith('/scene-templates')) return route.fulfill({ json: [{ id: 'shed', code: capabilities.code, name: capabilities.title, defaults: {}, description: '室外案例', capabilities }] })
    if (path.endsWith('/scenes')) return route.fulfill({ json: [scene()] })
    if (path.endsWith('/map-objects') || path.endsWith('/fire-sources')) return route.fulfill({ json: sources })
    if (path.endsWith('/preview')) { reads++; return route.fulfill({ json: preview(request.method() === 'POST' ? request.postDataJSON() : saved) }) }
    if (path.endsWith('/parameters')) {
      if (failSave) return route.fulfill({ status: 503, json: { detail: '保存失败，请重试。' } })
      writes++; saved = request.postDataJSON(); return route.fulfill({ json: scene() })
    }
    return route.fulfill({ status: 404, json: { detail: 'Fixture route not defined' } })
  })
  const base = process.env.QA_BASE_URL || 'http://127.0.0.1:5181'
  for (const [width, height] of [[1440, 900], [1366, 650], [390, 844]]) {
    saved = { ...initial }; failSave = false
    await page.setViewportSize({ width, height })
    await page.goto(base + '/tests/scenario-preparation.html?scene=select-source&preparation=2')
    const select = page.getByLabel('充电棚对象', { exact: true })
    await select.waitFor(); await page.waitForFunction(() => !document.querySelector('#fire-source')?.disabled)
    const canvas = page.locator('.scene-live-preview canvas').last(); await canvas.waitFor()
    await canvas.scrollIntoViewIfNeeded()
    await page.waitForFunction(() => document.querySelector('.scene-live-preview canvas')?.width > 10)
    const bounds = await canvas.boundingBox()
    assert.ok(bounds.height >= 200, `Three-dimensional picker too short at ${width}: ${bounds.height}px`)
    const camera = new PerspectiveCamera(48, bounds.width / bounds.height, .1, 400)
    camera.position.set(66, 76, 74); camera.lookAt(0, 0, 0); camera.updateMatrixWorld()
    const position = new Vector3(20, 2.6, 15).project(camera)
    await page.mouse.click(bounds.x + (position.x + 1) * bounds.width / 2, bounds.y + (1 - position.y) * bounds.height / 2)
    await page.waitForFunction(() => document.querySelector('#fire-source')?.value === 'west')
    await page.getByText('巡检与断电目标：西侧备用充电棚', { exact: true }).waitFor()
    assert.ok(await page.getByRole('button', { name: '撤销火点选择', exact: true }).isEnabled())
    await page.getByRole('button', { name: '撤销火点选择', exact: true }).click()
    assert.equal(await select.inputValue(), 'east')
    await select.selectOption('west')
    await page.getByText('巡检与断电目标：西侧备用充电棚', { exact: true }).waitFor()
    failSave = true
    await page.getByRole('button', { name: '保存场景参数', exact: true }).click()
    await page.getByRole('alert').filter({ hasText: '保存失败' }).waitFor()
    assert.equal(await select.inputValue(), 'west', 'Failed save must preserve the chosen draft')
    failSave = false
    await page.getByRole('button', { name: '保存场景参数', exact: true }).click()
    await page.getByText('参数已保存，新场次将冻结此火点。', { exact: true }).waitFor()
    assert.ok(await page.getByRole('button', { name: '撤销火点选择', exact: true }).isDisabled())
    assert.ok(await page.locator('main').evaluate(el => el.scrollWidth <= el.clientWidth + 1))
    assert.ok(await page.locator('.atlas-preparation__inspector').evaluate(el => el.scrollWidth <= el.clientWidth + 1))
    await page.locator('.scene-live-preview').scrollIntoViewIfNeeded()
    await page.screenshot({ path: resolve(output, `fire-source-${width}.png`), fullPage: true })
    await page.reload(); await select.waitFor(); await page.waitForFunction(() => !document.querySelector('#fire-source')?.disabled)
    assert.equal(await select.inputValue(), 'west', 'Saved selection must be restored on reload')
  }
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ checks: ['真实三维射线点选', '列表同步', '撤销', '失败保留草稿', '保存及刷新恢复', '桌面/短屏/手机布局'], reads, writes, errors, output }, null, 2))
} finally { await browser.close() }
