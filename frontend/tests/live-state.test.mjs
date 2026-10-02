import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'

const source = fs.readFileSync(new URL('../src/api/live.ts', import.meta.url), 'utf8')
const code = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
const { applyLiveMessage, isNewerState } = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'))

test('late socket or HTTP state cannot revert an accepted command', () => {
  const current = { id: 'drill', state_version: '12:30' }
  assert.equal(isNewerState({ id: 'drill', state_version: '11:40' }, current), false)
  assert.equal(isNewerState({ id: 'drill', state_version: '12:29' }, current), false)
  assert.equal(isNewerState({ id: 'drill', state_version: '13:30' }, current), true)
})

test('delta preserves static geometry and updates people, score and command together', () => {
  const prior = { id: 'drill', state_version: '12:30', simulation: { world: { building: 1 }, residents: [{ id: 'a', x: 1 }], summary: { evacuated: 0 } }, score: 10 }
  const next = applyLiveMessage(prior, { type: 'drill.delta', drill_id: 'drill', base_version: '12:30', state_version: '13:31', patch: [
    { path: ['state_version'], value: '13:31' }, { path: ['simulation', 'residents'], value: [{ id: 'a', x: 2 }] }, { path: ['score'], value: 15 }, { path: ['command'], value: { status: 'executing' } },
  ] })
  assert.deepEqual(next.simulation.world, prior.simulation.world)
  assert.equal(next.simulation.world, prior.simulation.world)
  assert.equal(next.simulation.residents[0].x, 2)
  assert.equal(prior.simulation.residents[0].x, 1)
  assert.equal(next.score, 15)
  assert.equal(next.command.status, 'executing')
})

test('missing baseline and sequence gaps require a fresh snapshot', () => {
  const message = { type: 'drill.delta', drill_id: 'drill', base_version: '12:30', state_version: '13:31', patch: [] }
  assert.throws(() => applyLiveMessage(null, message))
  assert.throws(() => applyLiveMessage({ id: 'drill', state_version: '10:30' }, message))
  assert.throws(() => applyLiveMessage({ id: 'another', state_version: '12:30' }, message))
  const fresh = { id: 'drill', state_version: '13:31' }
  assert.equal(applyLiveMessage(null, { type: 'drill.snapshot', data: fresh }), fresh)
})

test('unsafe patch paths cannot mutate prototypes', () => {
  assert.throws(() => applyLiveMessage({ id: 'drill', state_version: '1:0' }, { type: 'drill.delta', drill_id: 'drill', base_version: '1:0', state_version: '2:0', patch: [{ path: ['__proto__', 'polluted'], value: true }] }))
  assert.equal({}.polluted, undefined)
})
