import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'

const source=fs.readFileSync(new URL('../src/domain/agent.ts',import.meta.url),'utf8')
const code=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText
const {canApplyAgentRun,buildingReleaseSignals}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'))

test('building signals require matching live authority and approved plans',()=>{
 const wave={wave:1,state:'waiting',reason:'等待有效喷水',buildings:[{id:'b1',name:'一号楼',total:3,arrived:0}]}
 const run={approved_revision:1,status:'executing',execution:{coordination:{release_waves:[wave]}}}
 const feed={id:'d1',source_version:'v1',runs:[run]}
 assert.equal(buildingReleaseSignals(feed,'d1','v1',false)[0].state,'waiting')
 for(const args of [[feed,'d1','v1',true],[feed,'d1','v2',false],[feed,'other','v1',false]])assert.deepEqual(buildingReleaseSignals(...args),[])
 assert.deepEqual(buildingReleaseSignals({...feed,runs:[{...run,approved_revision:null}]},'d1','v1',false),[])
 assert.deepEqual(buildingReleaseSignals({...feed,runs:[{...run,status:'taken_over'}]},'d1','v1',false),[])
})

test('delayed socket frames cannot undo an HTTP-confirmed revision or a newly created plan',()=>{
  const current={id:'r',revision:3,created_at_us:100,updated_at_us:300,at_seconds:12}
  assert.equal(canApplyAgentRun({...current,revision:2,at_seconds:14},current),false)
  assert.equal(canApplyAgentRun({...current,updated_at_us:299},current),false)
  assert.equal(canApplyAgentRun({...current,at_seconds:11},current),false)
  assert.equal(canApplyAgentRun({...current,id:'old',created_at_us:99,updated_at_us:400},current),false)
  assert.equal(canApplyAgentRun({...current,updated_at_us:301},current),true)
})
