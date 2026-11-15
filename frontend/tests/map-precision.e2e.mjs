// Disposable QA API only: HTML validation and the persisted payload are both checked.
import assert from 'node:assert/strict'

const {default:playwright}=await import(process.env.PLAYWRIGHT_MODULE||'playwright')
assert.ok(process.env.QA_PASSWORD,'QA_PASSWORD is required for an isolated database')
const api=process.env.QA_API_URL||'http://127.0.0.1:8033/api/v1'
const base=process.env.QA_BASE_URL||'http://127.0.0.1:5195'
const browser=await playwright.chromium.launch({headless:true,
  ...(process.env.QA_BROWSER_PATH?{executablePath:process.env.QA_BROWSER_PATH}:{})})
const context=await browser.newContext({viewport:{width:1440,height:900}})
let objectPath,nodePath,originalNode,headers
async function request(path,method='GET',data){
  const response=await context.request.fetch(api+path,{method,headers,data})
  assert.ok(response.ok(),`${method} ${path}: ${response.status()}`)
  return response.status()===204?null:response.json()
}
try{
  const login=await request('/auth/login','POST',{username:'admin',password:process.env.QA_PASSWORD})
  headers={Authorization:'Bearer '+login.access_token}
  const demo=await request('/communities/demo-ready','POST',{})
  const root='/communities/'+demo.community.id
  const name='精确坐标与属性验收'
  const properties={capacity:55,width:2.4,note:'原始备注',equipment:{revision:3,inlet:'left'}}
  const object=await request(root+'/map-objects','POST',{
    object_type:'fire_hydrant',name,geometry:{x:11,y:11},properties})
  objectPath=root+'/map-objects/'+object.id
  const page=await context.newPage()
  await page.goto(base+root+'/map')
  await page.getByRole('button',{name:new RegExp('^'+name+'，')}).click()
  await page.getByRole('textbox',{name:'现场备注 可选',exact:true}).fill('只修改备注，保留设备参数')
  await page.getByRole('button',{name:'保存对象属性',exact:true}).click()
  await page.getByText('对象属性与位置已保存。',{exact:true}).waitFor()
  let saved=(await request(root+'/map-objects')).find(x=>x.id===object.id)
  assert.deepEqual(saved.geometry,{x:11,y:11},'Saving an odd coordinate must not force a grid snap')
  assert.deepEqual(saved.properties,{...properties,note:'只修改备注，保留设备参数'})
  await page.locator('#object-x').fill('11.25')
  await page.locator('#object-y').fill('11.75')
  await page.getByRole('textbox',{name:'现场备注 可选',exact:true}).fill('')
  const savedObject=page.waitForResponse(r=>r.url()===api+objectPath&&r.request().method()==='PATCH')
  await page.getByRole('button',{name:'保存对象属性',exact:true}).click()
  assert.ok((await savedObject).ok())
  saved=(await request(root+'/map-objects')).find(x=>x.id===object.id)
  assert.deepEqual(saved.geometry,{x:11.25,y:11.75})
  const {note,...retained}=properties
  assert.deepEqual(saved.properties,retained,'Clearing the note cannot erase model or equipment data')
  await page.reload()
  await page.getByRole('button',{name:new RegExp('^'+name+'，')}).click()
  assert.equal(await page.locator('#object-x').inputValue(),'11.25')
  const node=(await request(root+'/road-network')).nodes[0]
  originalNode={x:node.x,y:node.y}
  nodePath=root+'/road-network/nodes/'+node.id
  await page.getByRole('tab',{name:'道路网络',exact:true}).click()
  await page.locator('.road-node').filter({hasText:node.name}).click()
  await page.locator('#node-x').fill('11.75')
  await page.locator('#node-y').fill('7.25')
  const savedNode=page.waitForResponse(r=>r.url()===api+nodePath&&r.request().method()==='PATCH')
  await page.locator('.network-form button[type=submit]').click()
  assert.ok((await savedNode).ok())
  const network=await request(root+'/road-network')
  assert.equal(network.nodes.find(n=>n.id===node.id).x,11.75)
  assert.equal(network.nodes.find(n=>n.id===node.id).y,7.25)
  console.log(JSON.stringify({checks:['odd coordinates save without relocation','model metadata survives note update and clearing','fractional object coordinates survive refresh','fractional road nodes persist']}))
}finally{
  if(nodePath)await request(nodePath,'PATCH',originalNode)
  if(objectPath)await request(objectPath,'DELETE')
  await browser.close()
}
