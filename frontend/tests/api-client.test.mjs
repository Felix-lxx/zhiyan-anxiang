import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'

const source = fs.readFileSync(new URL('../src/api/client.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
const { createApiClient, ApiError, setTokenRefreshHandler, setUnauthorizedHandler } = await import('data:text/javascript;base64,' + Buffer.from(compiled).toString('base64'))

test('JSON mutation uses current token and preserves payload', async t => {
  let token='first'
  t.mock.method(globalThis,'fetch',async(url,options)=>{
    assert.equal(url,'https://example.test/api/v1/scenes')
    assert.equal(options.headers.get('Authorization'),'Bearer second')
    assert.equal(options.headers.get('Content-Type'),'application/json')
    assert.deepEqual(JSON.parse(options.body),{resident_count:27})
    return new Response('{"id":"saved"}',{status:201})
  })
  const api=createApiClient('https://example.test/api/v1/',()=>token)
  token='second'
  assert.deepEqual(await api.post('/scenes',{resident_count:27}),{id:'saved'})
})

test('expired operator session notifies once; public invite 401 does not log out operator',async t=>{
  let count=0;setUnauthorizedHandler(()=>count++)
  t.mock.method(globalThis,'fetch',async(_url,options)=>new Response('{"detail":"凭证无效"}',{status:401}))
  const api=createApiClient('https://example.test/api/v1',()=> 'operator')
  await assert.rejects(api.get('/auth/me'), error=>error instanceof ApiError && error.status===401)
  assert.equal(count,1)
  await assert.rejects(api.get('/participant/drills/1?code=invalid'))
  assert.equal(count,1)
})

test('public request never sends operator credentials',async t=>{
  t.mock.method(globalThis,'fetch',async(_url,options)=>{
    assert.equal(options.headers.has('Authorization'),false)
    return new Response('{}')
  })
  await createApiClient('https://example.test/api/v1',()=> 'private').post('/participant/drills/1/join?code=invite',{role:'居民代表'})
})

test('validation detail, 204 and cancelled request have distinct outcomes',async t=>{
  const api=createApiClient('https://example.test/api/v1')
  t.mock.method(globalThis,'fetch',async()=>new Response('{"detail":[{"msg":"人数超出范围"}]}',{status:422}))
  await assert.rejects(api.post('/preview',{}),{message:'人数超出范围'})
  globalThis.fetch=async()=>new Response(null,{status:204})
  assert.equal(await api.delete('/objects/1'),null)
  const controller=new AbortController();controller.abort()
  globalThis.fetch=async(_url,options)=>{options.signal.throwIfAborted()}
  await assert.rejects(api.get('/preview',{signal:controller.signal}),{name:'AbortError'})
})

test('expired access token refreshes once and retries with the new token',async t=>{
  let calls=0, token='expired'
  setTokenRefreshHandler(async()=>{token='renewed';return token})
  t.mock.method(globalThis,'fetch',async(_url,options)=>{
    calls++
    assert.equal(options.credentials,'include')
    if(calls===1){assert.equal(options.headers.get('Authorization'),'Bearer expired');return new Response('{"detail":"expired"}',{status:401})}
    assert.equal(options.headers.get('Authorization'),'Bearer renewed')
    return new Response('{"ok":true}')
  })
  const api=createApiClient('https://example.test/api/v1',()=>token)
  assert.deepEqual(await api.get('/auth/me'),{ok:true})
  assert.equal(calls,2)
  setTokenRefreshHandler(async()=>null)
})
