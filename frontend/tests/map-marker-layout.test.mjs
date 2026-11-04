import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'

const source = fs.readFileSync(new URL('../src/domain/map-marker-layout.ts', import.meta.url), 'utf8')
const code = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
const { groupMapMarkers } = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'))
const objects = [
  { id:'building', geometry:{x:20,y:30} },
  { id:'hydrant', geometry:{x:25,y:35} },
  { id:'shed', geometry:{x:33,y:40} },
  { id:'exit', geometry:{x:80,y:90} },
]
test('compact target groups remain accessible without moving real map objects', () => {
  const original=structuredClone(objects)
  const groups=groupMapMarkers(objects,320,520,true,'hydrant')
  assert.equal(groups.length,2)
  assert.equal(groups[0].object.id,'hydrant')
  assert.deepEqual(groups.flatMap(group=>group.members).map(item=>item.id).sort(),objects.map(item=>item.id).sort())
  assert.deepEqual(objects,original)
  for(let i=0;i<groups.length;i++)for(let j=i+1;j<groups.length;j++){
    const a=groups[i].object.geometry,b=groups[j].object.geometry
    assert.ok(Math.abs(a.x-b.x)*3.2>=48||Math.abs(a.y-b.y)*5.2>=48)
  }
  assert.equal(groupMapMarkers(objects,900,600,false,null).length,objects.length)
})
