import * as THREE from 'three'

export interface AssemblyResident {
  id: string
  status: string
  node_id?: string
  counted?: boolean
  exit?: 'north' | 'south'
}

/** Arrival is authoritative, never inferred from proximity or a route assignment. */
export function assemblyAttendance(residents: AssemblyResident[], nodeId: string) {
  const arrived = residents.filter(person => person.status === 'evacuated' && (person.node_id === nodeId || person.node_id?.startsWith(`${nodeId}:`)))
  const counted = arrived.filter(person => person.counted).length
  const side = nodeId === 'assembly:north' ? 'north' : nodeId === 'assembly:south' ? 'south' : null
  const inbound = side ? residents.filter(person => person.exit === side && person.status !== 'evacuated').length : 0
  return { arrived: arrived.length, counted, pending: arrived.length - counted, inbound }
}

/** Wayfinding only; does not add invisible obstacles or change simulation capacity. */
export function createAssemblyPoint(name: string) {
  const group = new THREE.Group()
  const paint = new THREE.MeshStandardMaterial({ color:0x70b793, roughness:.9 })
  const steel = new THREE.MeshStandardMaterial({ color:0x9bada1, metalness:.55, roughness:.4 })
  const plinth = new THREE.Mesh(new THREE.BoxGeometry(5.2,.035,4.4),new THREE.MeshStandardMaterial({color:0x3b6254,roughness:.95}))
  plinth.position.y=.028; plinth.receiveShadow=true; group.add(plinth)
  for(const side of [-1,1]) {
    const border=new THREE.Mesh(new THREE.BoxGeometry(5.2,.02,.09),paint); border.position.set(0,.058,side*2.15); group.add(border)
    const edge=new THREE.Mesh(new THREE.BoxGeometry(.09,.02,4.4),paint); edge.position.set(side*2.55,.058,0); group.add(edge)
    const post=new THREE.Mesh(new THREE.CylinderGeometry(.045,.045,3.4,8),steel);post.position.set(side*1.3,1.7,-2.1);post.castShadow=true;group.add(post)
    const foot=new THREE.Mesh(new THREE.BoxGeometry(.25,.07,.25),steel);foot.position.set(side*1.3,.05,-2.1);group.add(foot)
  }
  const canvas=document.createElement('canvas');canvas.width=768;canvas.height=256
  const context=canvas.getContext('2d')!
  const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace
  const panel=new THREE.Mesh(new THREE.PlaneGeometry(3.9,1.3),new THREE.MeshBasicMaterial({map:texture,side:THREE.DoubleSide,toneMapped:false}))
  panel.position.set(0,3,-2.08);group.add(panel)
  const frame=new THREE.Mesh(new THREE.BoxGeometry(4.04,1.44,.08),steel);frame.position.set(0,3,-2.16);group.add(frame)
  const back=panel.clone();back.position.z=-2.21;back.rotation.y=Math.PI;group.add(back)
  let signature=''
  function update(counts: ReturnType<typeof assemblyAttendance> | null) {
    const next=counts ? `${counts.arrived}/${counts.counted}/${counts.inbound}` : 'untracked'
    if(signature===next)return
    signature=next
    context.fillStyle='#174d3e';context.fillRect(0,0,768,256)
    context.strokeStyle='#b8dac4';context.lineWidth=5;context.strokeRect(8,8,752,240)
    context.fillStyle='#f2f5e8';context.textAlign='center';context.textBaseline='middle'
    context.font='600 54px "Microsoft YaHei", sans-serif';context.fillText(name,384,70,720)
    context.font='500 42px "Microsoft YaHei", sans-serif'
    context.fillText(counts ? `到达 ${counts.arrived} 人 · 已清点 ${counts.counted} 人` : '集合后逐人核验',384,153,720)
    context.font='32px "Microsoft YaHei", sans-serif'
    context.fillText(counts ? `待核验 ${counts.pending} 人 · 未到 ${counts.inbound} 人` : '以服务端到达记录为准',384,211,720)
    texture.needsUpdate=true
  }
  update(null)
  return { group, update }
}
