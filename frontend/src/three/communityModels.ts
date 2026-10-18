import * as THREE from 'three'
import type { SceneMaterials } from './sceneMaterials'

function surface(color: number, roughness = .86) {
  return new THREE.MeshStandardMaterial({ color, roughness })
}

function box(group: THREE.Group, dimensions: [number,number,number], position: [number,number,number], color: number) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...dimensions), surface(color))
  mesh.position.set(...position); mesh.castShadow = true; mesh.receiveShadow = true; group.add(mesh)
  return mesh
}

function sign(group: THREE.Group, text: string, width: number, y: number, z: number, background = '#245346') {
  const canvas=document.createElement('canvas');canvas.width=512;canvas.height=96
  const ctx=canvas.getContext('2d')!;ctx.fillStyle=background;ctx.fillRect(0,0,512,96)
  ctx.fillStyle='#efe8d2';ctx.font='600 42px "Microsoft YaHei", sans-serif';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(text,256,48,490)
  const map=new THREE.CanvasTexture(canvas);map.colorSpace=THREE.SRGBColorSpace
  const panel=new THREE.Mesh(new THREE.PlaneGeometry(width,width*96/512),new THREE.MeshStandardMaterial({map,roughness:.7,emissive:0x24241d,emissiveMap:map,emissiveIntensity:.15}))
  panel.position.set(0,y,z);group.add(panel)
}

/** Repeated facade elements use one draw call per material, including distant views. */
function instances(group: THREE.Group, geometry: THREE.BufferGeometry, material: THREE.Material, placements: Array<[number,number,number,number]>) {
  const mesh = new THREE.InstancedMesh(geometry, material, placements.length)
  const transform = new THREE.Object3D()
  placements.forEach(([x,y,z,rotation], i) => {
    transform.position.set(x,y,z); transform.rotation.set(0,rotation,0); transform.updateMatrix()
    mesh.setMatrixAt(i,transform.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true; mesh.castShadow = true; mesh.receiveShadow = true; group.add(mesh)
}

export function createApartment(width: number, depth: number, floors: number, seed: number, night: boolean, materials?: SceneMaterials) {
  const lod = new THREE.LOD()
  const colors = [0xb3ae9f, 0xc0b29f, 0x9ba9a4, 0xb7ab9c]
  const height = floors * 3.2
  for (const detailed of [true,false]) {
    const group = new THREE.Group()
    // Hollow envelope with an actual south-facing opening shared by both LODs.
    // A solid box behind a decorative door made every exiting resident cross a wall.
    const doorway = Math.min(1.8, width - .4), wall = .12
    const shellParts = [
      box(group,[wall,height,depth],[-width/2+wall/2,height/2,0],colors[seed % colors.length]!),
      box(group,[wall,height,depth],[width/2-wall/2,height/2,0],colors[seed % colors.length]!),
      box(group,[width,height,wall],[0,height/2,-depth/2+wall/2],colors[seed % colors.length]!),
      box(group,[(width-doorway)/2,height,wall],[-(width+doorway)/4,height/2,depth/2-wall/2],colors[seed % colors.length]!),
      box(group,[(width-doorway)/2,height,wall],[(width+doorway)/4,height/2,depth/2-wall/2],colors[seed % colors.length]!),
      box(group,[doorway,height-2.55,wall],[0,(height+2.55)/2,depth/2-wall/2],colors[seed % colors.length]!),
    ]
    for (const shell of shellParts) {
      shell.name = 'building-envelope'
      if (materials) { shell.material.dispose(); shell.material = materials.surface('plaster', colors[seed % colors.length]!, Math.max(1,width/4), floors).clone() }
    }
    box(group,[width+.45,.25,depth+.45],[0,height+.12,0],0x6b7770)
    for (const side of [-1,1]) {
      box(group,[width+.45,.8,.18],[0,height+.5,side*depth/2],0x979e91)
      box(group,[.18,.8,depth],[side*width/2,height+.5,0],0x979e91)
    }
    const columns = Math.max(2,Math.floor(width/2.3))
    const dark: Array<[number,number,number,number]> = [], lit: typeof dark = [], ac: typeof dark = [], ledges: typeof dark = []
    const verticalFrames: typeof dark = [], horizontalFrames: typeof dark = [], railings: typeof dark = [], balconySlabs: typeof dark = [], balconyBars: typeof dark = [], grilles: typeof dark = []
    for (let floor=0;floor<floors;floor++) {
      if (detailed) box(group,[width+.1,.09,depth+.1],[0,(floor+1)*3.2-.1,0],0x90998e)
      for (const side of [-1,1]) for(let col=0;col<columns;col++) {
        const x = (col-(columns-1)/2)*(width/(columns+1))
        if (floor === 0 && side === 1 && Math.abs(x) < doorway/2+.8) continue
        const y = floor*3.2+1.8, z = side*(depth/2+.04)
        const target = night && (floor*7+col+seed)%5 < 2 ? lit : dark
        target.push([x,y,z,side === -1 ? Math.PI : 0])
        if(detailed) {
          ledges.push([x,y-.8,z+side*.14,0])
          if(col%2===0) ac.push([x+.65,y-.8,z+side*.28,0])
          for (const dx of [-.51,0,.51]) verticalFrames.push([x+dx,y,z+side*.07,0])
          for (const dy of [-.7,.7]) horizontalFrames.push([x,y+dy,z+side*.07,0])
          if (floor > 0 && col % 3 === 1) {
            balconySlabs.push([x,y-.86,z+side*.43,0]); railings.push([x,y-.12,z+side*.88,0])
            for (let bar=-3;bar<=3;bar++) balconyBars.push([x+bar*.21,y-.46,z+side*.88,0])
          } else if (floor < 2) {
            for (let bar=-2;bar<=2;bar++) grilles.push([x+bar*.19,y,z+side*.15,0])
          }
        }
      }
      for(const side of [-1,1]) dark.push([side*(width/2+.04),floor*3.2+1.8,0,Math.PI/2])
    }
    instances(group,new THREE.BoxGeometry(.95,1.35,.07),surface(0x314e57,.35),dark)
    instances(group,new THREE.BoxGeometry(.95,1.35,.07),new THREE.MeshStandardMaterial({color:0xe5c185,emissive:0xe5a554,emissiveIntensity:night?.65:0,roughness:.6}),lit)
    if(detailed) {
      instances(group,new THREE.BoxGeometry(1.15,.12,.4),surface(0xddd8c5),ledges)
      instances(group,new THREE.BoxGeometry(.55,.4,.38),surface(0xaab3b0),ac)
      instances(group,new THREE.BoxGeometry(.055,1.46,.09),surface(0xd0cec2,.48),verticalFrames)
      instances(group,new THREE.BoxGeometry(1.08,.06,.09),surface(0xd0cec2,.48),horizontalFrames)
      instances(group,new THREE.BoxGeometry(1.55,.12,.98),surface(0xada99d),balconySlabs)
      instances(group,new THREE.BoxGeometry(1.55,.055,.055),surface(0x485953,.45),railings)
      instances(group,new THREE.BoxGeometry(.035,.74,.035),surface(0x485953,.45),balconyBars)
      instances(group,new THREE.BoxGeometry(.025,1.38,.025),surface(0x7c817b,.45),grilles)
      const fans: typeof dark = ac.map(([x,y,z,r])=>[x,y,z+(z>0?.205:-.205),r])
      instances(group,new THREE.CylinderGeometry(.14,.14,.025,12).rotateX(Math.PI/2),surface(0x414f4f,.6),fans)
      box(group,[width*.35,1.5,depth*.38],[0,height+.9,0],0x939c91)
      const tank=new THREE.Mesh(new THREE.CylinderGeometry(.65,.65,1.1,16),new THREE.MeshStandardMaterial({color:0xaeb8b1,roughness:.4,metalness:.6}));tank.position.set(-width*.28,height+.8,0);tank.castShadow=true;group.add(tank)
      for(const x of [-width/2+.25,width/2-.25]) box(group,[.08,height,.1],[x,height/2,depth/2+.1],0x647872)
      box(group,[.12,height,.12],[width/2-.45,height/2,-depth/2-.12],0x7e7c6e)
      for(let level=0;level<floors;level++) box(group,[.2,.08,.15],[width/2-.45,level*3.2+1,-depth/2-.12],0x575b54)
    }
    // Door leaves are held against the jambs, outside the traversable opening.
    for (const side of [-1,1]) {
      box(group,[.07,2.5,.68],[side*(doorway/2+.06),1.25,depth/2+.2],0x254e4c)
      box(group,[.10,2.55,.14],[side*(doorway/2+.02),1.275,depth/2],0x697e72)
    }
    box(group,[Math.min(width,2.8),.15,1.2],[0,2.7,depth/2+.4],0x798a80)
    // Both levels retain windows. Only small fixtures disappear in overview.
    lod.addLevel(group,detailed?0:90, .12)
  }
  return lod
}

export function createChargingShed(width: number, depth: number) {
  const group = new THREE.Group()
  box(group,[width+.5,.15,depth+.5],[0,.08,0],0x9ba396)
  box(group,[width+.8,.2,depth+.65],[0,2.75,0],0x577d77)
  const ribs: Array<[number,number,number,number]> = []
  for(let x=-width/2;x<=width/2;x+=.35) ribs.push([x,2.88,0,0])
  instances(group,new THREE.BoxGeometry(.04,.055,depth+.65),surface(0x7c9490,.45),ribs)
  box(group,[width,.12,.12],[0,2.35,-depth/2+.18],0x3f504a)
  sign(group,'集中充电 · 禁止烟火',Math.min(width,5),2.53,depth/2+.35)
  for(const x of [-width/2+.2,width/2-.2]) for(const z of [-depth/2+.2,depth/2-.2]) box(group,[.12,2.7,.12],[x,1.4,z],0x748a83)
  const count=Math.max(2,Math.floor(width/1.3))
  for(let i=0;i<count;i++) {
    const x=(i-(count-1)/2)*(width/(count+1))
    box(group,[.32,.65,.16],[x,1.2,-depth/2+.2],0xeee6cf)
    box(group,[.12,.12,.025],[x,1.3,-depth/2+.29],0x31574e)
    box(group,[.3,.12,.46],[x,1.03,.05],0x293631)
    box(group,[.36,.25,.8],[x,.8,0],0x55777a)
    for(const z of [-.4,.4]) {
      const wheel=new THREE.Mesh(new THREE.TorusGeometry(.25,.07,6,12),surface(0x26312d))
      wheel.rotation.y=Math.PI/2;wheel.position.set(x,.4,z);group.add(wheel)
    }
    box(group,[.06,.5,.06],[x,.9,-.4],0xadb8ac)
    box(group,[.48,.06,.06],[x,1.15,-.4],0x3d5550)
  }
  return group
}

export function createFireStation(width: number, depth: number) {
  const group=new THREE.Group()
  box(group,[width,2.8,depth],[0,1.4,0],0xc0bfb1)
  box(group,[width+.25,.24,depth+.25],[0,2.92,0],0x884e40)
  box(group,[width*.55,2.2,.12],[0,1.1,depth/2+.07],0x416b66)
  box(group,[width,.3,.15],[0,2.55,depth/2+.08],0xa44335)
  sign(group,'微型消防站',Math.min(width*.9,4),2.55,depth/2+.17,'#883e31')
  for(let y=.25;y<2.2;y+=.18) box(group,[width*.54,.025,.04],[0,y,depth/2+.15],0x82938b)
  for(const x of [-width*.4,width*.4]) { box(group,[.24,.65,.2],[x,.4,depth/2+.22],0xac3c29); box(group,[.07,.16,.09],[x,.81,depth/2+.22],0x303b37) }
  return group
}

/** Small-scale fixtures remain outside navigation corridors; placement is validated by the arena. */
export function createStreetFurniture() {
  const group=new THREE.Group()
  for(const x of [-.7,.7]) {
    box(group,[.09,.65,.65],[x,.35,0],0x425c50)
    box(group,[.08,.4,.08],[x,.85,.27],0x425c50)
  }
  for(let i=0;i<5;i++)box(group,[1.8,.065,.095],[0,.68,(i-2)*.12],0x927258)
  for(let i=0;i<3;i++)box(group,[1.8,.095,.07],[0,.85+i*.14,.3],0x927258)
  for(const x of [-1.55,-2.2]) {
    box(group,[.47,.75,.47],[x,.38,.05],x<-2?0x516f63:0x687c86)
    box(group,[.52,.075,.52],[x,.79,.05],0x344940)
    box(group,[.19,.09,.025],[x,.67,-.195],0xbfc9bd)
  }
  return group
}

/** Physical pavement stays stable while the separate risk layer changes. */
export function createStreet(length: number, width: number, materials?: SceneMaterials) {
  const group = new THREE.Group()
  const road = box(group,[width,.1,length],[0,.02,0],0x505a57)
  if(materials) { road.material.dispose(); road.material = materials.surface('asphalt',0x737774,Math.max(1,width/3),Math.max(1,length/3)) }
  for(const side of [-1,1]) box(group,[.3,.17,length],[side*(width/2+.18),.1,0],0xa4aca0)
  const marks: Array<[number,number,number,number]>=[]
  for(let z=-length/2+1.5;z<length/2-1;z+=3.5) marks.push([0,.09,z,0])
  instances(group,new THREE.BoxGeometry(.09,.02,1.5),surface(0xd8d3b5),marks)
  if(length>8) {
    const cover=new THREE.Mesh(new THREE.CylinderGeometry(.42,.42,.025,24),surface(0x414944,.8)); cover.position.set(width*.22,.084,Math.min(3,length*.2));group.add(cover)
    const grooves: Array<[number,number,number,number]> = []
    for(let i=-3;i<=3;i++)grooves.push([width*.22,.101,Math.min(3,length*.2)+i*.09,0])
    instances(group,new THREE.BoxGeometry(.52,.012,.018),surface(0x788079),grooves)
  }
  return group
}

/** Road-aligned closure equipment; width comes from the actual blocked edge. */
export function createRoadBarrier(width: number) {
  const group = new THREE.Group()
  const span = Math.max(.6, Math.min(20, width * .9))
  box(group, [span, .34, .09], [0, .92, 0], 0xe4dfce)
  const stripes: Array<[number,number,number,number]> = []
  const count = Math.max(2, Math.floor(span / .4))
  for (let i = 0; i < count; i++) if (i % 2 === 0) stripes.push([-span/2 + (i+.5)*span/count, .92, .055, 0])
  instances(group, new THREE.BoxGeometry(span/count*.85, .32, .02), surface(0xb94d37, .48), stripes)
  for (const x of [-span*.39, span*.39]) {
    box(group, [.055, .93, .055], [x, .49, 0], 0x52605b)
    box(group, [.3, .075, .6], [x, .04, 0], 0x34413b)
    const lamp = new THREE.Mesh(new THREE.SphereGeometry(.075, 10, 8), new THREE.MeshStandardMaterial({color:0xe9b650,emissive:0x8a5718,emissiveIntensity:.6,roughness:.4}))
    lamp.position.set(x, 1.19, 0); group.add(lamp)
  }
  return group
}
