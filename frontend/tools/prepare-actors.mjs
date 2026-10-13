// Run with the local Vite server. Uses a browser for DOMParser/GLTFExporter;
// never imports or executes code from the downloaded model packages.
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ headless: true, ...(process.env.QA_BROWSER_PATH ? { executablePath: process.env.QA_BROWSER_PATH } : {}) })
try {
  const page = await browser.newPage()
  await page.goto((process.env.QA_BASE_URL || 'http://127.0.0.1:5173') + '/tools/prepare-actors.html')
  await page.waitForFunction(() => typeof window.prepareActors === 'function')
  const result = await page.evaluate(() => window.prepareActors())
  for (const [key, name] of [['robot', 'husky-parts.glb'], ['person', 'resident-casual.glb'], ['helper', 'helper-worker.glb']]) {
    const data = Buffer.from(result[key], 'base64')
    writeFileSync(fileURLToPath(new URL('../public/assets/actors/' + name, import.meta.url)), data)
    console.log(name, data.length, 'bytes')
  }
  console.log(JSON.stringify(result.report, null, 2))
} finally { await browser.close() }
