import test from 'node:test'
import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'

test('all shipped kitchen GLBs are self-contained and have renderable meshes',async()=>{
  for(const name of ['kitchenFridge','kitchenSink','kitchenCabinetDrawer','kitchenStove','kitchenCabinetUpper']){
    const data=await readFile(new URL(`../public/assets/kitchen/${name}.glb`,import.meta.url))
    assert.equal(data.toString('ascii',0,4),'glTF')
    assert.equal(data.readUInt32LE(4),2)
    assert.equal(data.readUInt32LE(8),data.length)
    const json=JSON.parse(data.toString('utf8',20,20+data.readUInt32LE(12)).trim())
    assert.ok(json.meshes?.length>0,name)
    for(const item of [...json.buffers??[],...json.images??[]])assert.ok(!item.uri||item.uri.startsWith('data:'),`${name} needs external ${item.uri}`)
  }
})
