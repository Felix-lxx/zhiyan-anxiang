// Real account page; browser-local protocol fixtures never touch real sessions.
import assert from 'node:assert/strict'
import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'

const { default: playwright } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await playwright.chromium.launch({ headless:true,
  ...(process.env.QA_BROWSER_PATH ? { executablePath:process.env.QA_BROWSER_PATH } : {}) })
const output = resolve('../output/playwright/account-security')
mkdirSync(output, { recursive:true })
try {
  const page = await browser.newPage(), errors = []
  page.on('pageerror', error => errors.push(error.message))
  const profile = { username:'layout-admin', role:'系统管理员', display_name:'布局验收', organization:'',
    default_community_id:null, text_size:'comfortable', reduced_motion:true, revision:1,
    updated_at:null, authentication_mode:'account_session' }
  let sessions = Array.from({ length:8 }, (_, index) => ({ id:`session-${index}`, current:index===0,
    status:'active', created_at:'2026-10-12T09:00:00+08:00',
    last_used_at:`2026-10-${String(18-index).padStart(2,'0')}T11:48:16+08:00`, expires_at:'2026-11-18T11:48:16+08:00' }))
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (path.endsWith('/auth/refresh')) return route.fulfill({ json:{ access_token:'isolated-layout-only', username:profile.username, role:profile.role, expires_in:3600 } })
    if (path.endsWith('/auth/me')) return route.fulfill({ json:{ username:profile.username, role:profile.role } })
    if (path.endsWith('/health')) return route.fulfill({ json:{ status:'healthy', database:{status:'healthy'} } })
    if (path.endsWith('/account/profile')) return route.fulfill({ json:profile })
    if (path.endsWith('/account/activity')) return route.fulfill({ json:{ community_count:0, drill_count:0, completed_count:0, unfinished_count:0, recent:[] } })
    if (path.endsWith('/auth/sessions')) return route.fulfill({ json:sessions })
    if (request.method()==='DELETE' && path.includes('/auth/sessions/')) {
      sessions = sessions.map(item => item.id===path.split('/').at(-1) ? {...item,status:'revoked'} : item)
      return route.fulfill({ status:204, body:'' })
    }
    return route.fulfill({ json:[] })
  })
  await page.goto((process.env.QA_BASE_URL || 'http://127.0.0.1:5173') + '/projects?section=account')
  const section = page.getByRole('region', { name:'登录与权限', exact:true })
  await section.getByText('8 个活动会话', { exact:true }).waitFor()
  for (const width of [1920,1440,1024,390]) {
    await page.setViewportSize({ width, height:width===390?844:1000 })
    await section.scrollIntoViewIfNeeded()
    const layout = await section.evaluate(element => {
      const overview = element.querySelector('.account-security-overview').getBoundingClientRect()
      const heading = element.querySelector('.account-session-heading').getBoundingClientRect()
      const list = element.querySelector('.account-session-list')
      return { width:element.clientWidth, columns:getComputedStyle(list).gridTemplateColumns.split(' ').length,
        separated:heading.top>=overview.bottom, overflow:document.documentElement.scrollWidth>innerWidth+1 }
    })
    assert.equal(layout.columns, layout.width>800?2:1)
    assert.equal(layout.separated, true, 'Summary stays above the full-width sessions')
    assert.equal(layout.overflow, false, `No horizontal overflow at ${width}`)
    const buttons = await section.getByRole('button', { name:'结束会话', exact:true }).all()
    for (const button of buttons) {
      const size = await button.boundingBox()
      assert.ok(size.height>=44, 'Session actions keep usable touch targets')
    }
    await section.screenshot({ path:resolve(output,`security-${width}.png`) })
  }
  await page.setViewportSize({ width:1440, height:1000 })
  page.once('dialog', dialog => dialog.accept())
  await section.getByRole('button', { name:'结束会话', exact:true }).first().click()
  await section.getByText('7 个活动会话', { exact:true }).waitFor()
  assert.equal(await section.getByRole('button', { name:'结束会话', exact:true }).count(),6)
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ checks:['Summary above two-column desktop sessions','Single-column tablet/mobile without overflow','44px actions and isolated revocation feedback'], errors, output },null,2))
} finally { await browser.close() }
