import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'

const moduleUrl = source => 'data:text/javascript;base64,' + Buffer.from(ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText).toString('base64')
const clientUrl = moduleUrl(fs.readFileSync(new URL('../src/api/client.ts', import.meta.url), 'utf8'))
const source = fs.readFileSync(new URL('../src/api/commands.ts', import.meta.url), 'utf8').replace("'./client'", JSON.stringify(clientUrl))
const { sendCommand, commandForPath } = await import(moduleUrl(source))
const { ApiError } = await import(clientUrl)

test('uncertain transport retries exactly the same command identity', async () => {
  const calls = []
  const api = { post: async (path, payload) => {
    calls.push({ path, payload })
    if (calls.length === 1) throw new TypeError('connection reset')
    return { state_version: '2:1' }
  } }
  assert.deepEqual(await sendCommand(api, 'drill', '/residents', { resident_ids: ['a'], exit: 'north' }), { state_version: '2:1' })
  assert.equal(calls.length, 2)
  assert.deepEqual(calls[0], calls[1])
  assert.equal(calls[0].path, '/drills/drill/commands')
})

test('domain rejection is not retried; uncertain result is not claimed to have failed', async () => {
  let calls = 0
  const rejected = { post: async () => { calls++; throw new ApiError('不可达', 409, null) } }
  await assert.rejects(sendCommand(rejected, 'drill', '/robot', {}), /不可达/)
  assert.equal(calls, 1)
  const disconnected = { post: async () => { throw new TypeError('offline') } }
  await assert.rejects(sendCommand(disconnected, 'drill', '/robot', {}), /结果暂未确认/)
})

test('road commands retain target and preview remains read-only transport', async () => {
  assert.equal(commandForPath('/roads/north/reopen').target_id, 'north')
  assert.equal(commandForPath('/spatial-preview', {}), null)
  const api = { request: async (path, options) => ({ path, options }) }
  const result = await sendCommand(api, 'drill', '/spatial-preview', { exit: 'north' })
  assert.equal(result.path, '/drills/drill/spatial-preview')
})

test('confirmed preview carries the exact event sequence through retries', async () => {
  const calls = []
  const api = { post: async (path, payload) => { calls.push({ path, payload }); return { state_version: '8:12' } } }
  await sendCommand(api, 'drill', '/robot', { command: 'move', x: 20, y: 30 }, 'POST', 7)
  assert.equal(calls[0].payload.expected_sequence, 7)
  assert.equal(calls[0].payload.kind, 'robot.command')
})
