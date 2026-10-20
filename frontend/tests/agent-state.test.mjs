import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'

const source=fs.readFileSync(new URL('../src/domain/agent.ts',import.meta.url),'utf8')
const code=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText
const {canApplyAgentRun}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'))

test('delayed socket frames cannot undo an HTTP-confirmed revision or a newly created plan',()=>{
  const current={id:'r',revision:3,created_at_us:100,updated_at_us:300,at_seconds:12}
  assert.equal(canApplyAgentRun({...current,revision:2,at_seconds:14},current),false)
  assert.equal(canApplyAgentRun({...current,updated_at_us:299},current),false)
  assert.equal(canApplyAgentRun({...current,at_seconds:11},current),false)
  assert.equal(canApplyAgentRun({...current,id:'old',created_at_us:99,updated_at_us:400},current),false)
  assert.equal(canApplyAgentRun({...current,updated_at_us:301},current),true)
})
