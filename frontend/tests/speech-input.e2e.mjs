// Real microphone capture/resampling + production UI; upstream transcript is an isolated fixture.
import assert from 'node:assert/strict'
import { mkdirSync } from 'node:fs'
const { default: playwright } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await playwright.chromium.launch({ headless: true,
  args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'],
  ...(process.env.QA_BROWSER_PATH ? { executablePath: process.env.QA_BROWSER_PATH } : {}),
})
const output = '../output/playwright/speech-input'
mkdirSync(output, { recursive: true })
try {
  const context = await browser.newContext({ permissions: ['microphone'] })
  const page = await context.newPage(), errors = []
  page.on('pageerror', e => errors.push(e.message))
  let uploads = 0, chatCalls = 0
  await page.route('**/speech-fixture/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/speech/status')) return route.fulfill({ json: { configured: true } })
    if (path.endsWith('/assistant/status')) return route.fulfill({ json: { configured: false } })
    if (path.endsWith('/agent/runs')) return route.fulfill({ json: { buildings: [], runs: [], drill_status: 'ready' } })
    if (path.endsWith('/speech/transcribe')) {
      const pcm = route.request().postDataBuffer()
      assert.ok(pcm.length >= 8000 && pcm.length <= 960000 && pcm.length % 2 === 0)
      assert.equal(route.request().headers()['content-type'], 'audio/pcm')
      uploads++
      return route.fulfill({ json: { text: '请查看三号楼重点人员。' } })
    }
    if (path.endsWith('/assistant/chat')) {chatCalls++;return route.fulfill({json:{mode:'offline',model:null,
      answer:'请先核对目标居民和通道状态，再预览疏散方案。',notice:'隔离界面协议响应，未调用模型。',
      context:{at_seconds:0,historical:false,selection:null},sources:[],actions:[]}})}
    return route.fulfill({ status: 404, json: { detail: 'unexpected fixture request' } })
  })
  for (const width of [390, 1366]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 650 })
    await page.goto((process.env.QA_BASE_URL || 'http://127.0.0.1:5173') + '/tests/speech-input.html')
    await page.locator('#scene-assistant-question').fill('原有问题')
    await page.getByRole('button', { name: '语音输入', exact: true }).click()
    await page.getByRole('button', { name: /结束并识别/ }).waitFor()
    await page.waitForFunction(()=>Number(document.querySelector('meter')?.value)>0)
    await page.screenshot({path:`${output}/recording-${width}.png`})
    await page.waitForTimeout(650)
    await page.getByRole('button', { name: /结束并识别/ }).click()
    await page.waitForFunction(() => document.querySelector('#scene-assistant-question').value.includes('三号楼'))
    assert.equal(await page.locator('#scene-assistant-question').inputValue(), '原有问题\n请查看三号楼重点人员。')
    assert.equal(chatCalls, 0, 'Transcription must never send a chat or command automatically')
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    await page.screenshot({ path: `${output}/assistant-${width}.png` })
    const before = uploads
    await page.getByRole('button', { name: '语音输入', exact: true }).click()
    await page.getByRole('button', { name: /结束并识别/ }).waitFor()
    await page.getByRole('button', { name: '取消', exact: true }).click()
    assert.equal(uploads, before, 'Cancelling must not upload audio')
    await page.locator('#scene-assistant-question').fill('优先护送三层重点居民，降低暴露')
    await page.getByRole('button', { name: '转为疏散目标', exact: true }).click()
    assert.equal(await page.getByLabel('演练目标',{exact:true}).inputValue(),'优先护送三层重点居民，降低暴露')
    assert.equal(chatCalls,0,'Draft handoff must not create a chat request or execute a plan')
    await page.getByRole('button', { name: '语音输入', exact: true }).waitFor()
    await page.screenshot({ path: `${output}/plan-${width}.png` })
  }
  await page.getByRole('button', { name: '场景对话', exact: true }).click()
  await page.evaluate(()=>{
    window.__originalMicrophone=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
    const audio=new AudioContext(),source=audio.createConstantSource(),destination=audio.createMediaStreamDestination()
    source.offset.value=0;source.connect(destination);source.start();void audio.resume();window.__silentAudio=audio
    navigator.mediaDevices.getUserMedia=async()=>destination.stream
  })
  const beforeSilence=uploads
  await page.getByRole('button',{name:'语音输入',exact:true}).click()
  await page.getByRole('button',{name:/结束并识别/}).waitFor();await page.waitForTimeout(650)
  await page.getByRole('button',{name:/结束并识别/}).click()
  await page.getByRole('alert').filter({hasText:'未检测到音频输入'}).waitFor()
  assert.equal(uploads,beforeSilence,'Digital silence must not be uploaded')
  await page.evaluate(()=>{navigator.mediaDevices.getUserMedia=window.__originalMicrophone;void window.__silentAudio.close()})
  await page.getByRole('button', { name: '场景对话', exact: true }).click()
  await page.locator('#scene-assistant-question').fill('现场情况')
  await page.locator('.scene-assistant__compose button[type=submit]').click()
  await page.getByRole('button',{name:'朗读这条回答',exact:true}).waitFor()
  await page.evaluate(()=>{
    window.speechSynthesis.speak=utterance=>{window.__spoken=utterance.text}
    window.speechSynthesis.cancel=()=>{window.__cancelled=(window.__cancelled||0)+1}
  })
  await page.getByRole('button',{name:'朗读这条回答',exact:true}).click()
  assert.ok(await page.evaluate(()=>window.__spoken.includes('核对目标居民')))
  await page.evaluate(() => {
    const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
    navigator.mediaDevices.getUserMedia = async constraints => {
      const stream = await original(constraints)
      window.__speechTracks = stream.getTracks()
      return stream
    }
  })
  await page.getByRole('button', { name: '语音输入', exact: true }).click()
  await page.getByRole('button', { name: /结束并识别/ }).waitFor()
  assert.ok(await page.evaluate(()=>window.__cancelled>=1),'Recording must stop the current speech playback')
  await page.getByRole('button', { name: '关闭 AI 助手', exact: true }).click()
  assert.ok(await page.evaluate(() => window.__speechTracks.every(track => track.readyState === 'ended')))
  await page.getByRole('button', { name: '打开助手', exact: true }).click()
  await page.getByRole('button', { name: '场景对话', exact: true }).click()
  await page.evaluate(() => {
    navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('denied', 'NotAllowedError'))
  })
  await page.getByRole('button', { name: '语音输入', exact: true }).click()
  await page.getByRole('alert').filter({ hasText: '未获得麦克风权限' }).waitFor()
  assert.equal(uploads, 2)
  assert.equal(chatCalls,1)
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ microphone: 'real browser synthetic device', uploads, chatCalls, widths: [390, 1366], pageErrors: errors }))
} finally { await browser.close() }
