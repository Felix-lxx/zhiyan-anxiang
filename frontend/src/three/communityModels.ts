import * as THREE from 'three'

function surface(color: number, roughness = .86) {
  return new THREE.MeshStandardMaterial({ color, roughness })
}

function box(group: THREE.Group, dimensions: [number,number,number], position: [number,number,number], color: number) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...dimensions), surface(color))
  mesh.position.set(...position); mesh.castShadow = true; mesh.receiveShadow = true; group.add(mesh)
  return mesh
}

/** Repeated facade elements use one draw call per material, including distant views. */
function instances(group: THREE.Group, geometry: THREE.BufferGeometry, material: THREE.Material, placements: Array<[number,number,number,number]>) {
  const mesh = new THREE.InstancedMesh(geometry, material, placements.length)
  const transform = new THREE.Object3D()
  placements.forEach(([x,y,z,rotation], i) => {
    transform.position.set(x,y,z); transform.rotation.set(0,rotation,0); transform.updateMatrix()
    mesh.setMatrixAt(i,transform.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true; group.add(mesh)
}

export function createApartment(width: number, depth: number, floors: number, seed: number, night: boolean) {
  const lod = new THREE.LOD()
  const colors = [0xb3ae9f, 0xc0b29f, 0x9ba9a4, 0xb7ab9c]
  const height = floors * 3.2
  for (const detailed of [true,false]) {
    const group = new THREE.Group()
    box(group,[width,height,depth],[0,height/2,0],colors[seed % colors.length]!)
    box(group,[width+.25,.8,depth+.25],[0,.4,0],0x707671)
    box(group,[width+.45,.25,depth+.45],[0,height+.12,0],0x6b7770)
    for (const side of [-1,1]) {
      box(group,[width+.45,.8,.18],[0,height+.5,side*depth/2],0x979e91)
      box(group,[.18,.8,depth],[side*width/2,height+.5,0],0x979e91)
    }
    const columns = Math.max(2,Math.floor(width/2.3))
    const dark: Array<[number,number,number,number]> = [], lit: typeof dark = [], ac: typeof dark = [], ledges: typeof dark = []
    for (let floor=0;floor<floors;floor++) {
      if (detailed) box(group,[width+.1,.09,depth+.1],[0,(floor+1)*3.2-.1,0],0x90998e)
      for (const side of [-1,1]) for(let col=0;col<columns;col++) {
        const x = (col-(columns-1)/2)*(width/(columns+1))
        const y = floor*3.2+1.8, z = side*(depth/2+.04)
        const target = night && (floor*7+col+seed)%5 < 2 ? lit : dark
        target.push([x,y,z,side === -1 ? Math.PI : 0])
        if(detailed) {
          ledges.push([x,y-.8,z+side*.14,0])
          if(col%2===0) ac.push([x+.65,y-.8,z+side*.28,0])
        }
      }
      for(const side of [-1,1]) dark.push([side*(width/2+.04),floor*3.2+1.8,0,Math.PI/2])
    }
    instances(group,new THREE.BoxGeometry(.95,1.35,.07),surface(0x314e57,.35),dark)
    instances(group,new THREE.BoxGeometry(.95,1.35,.07),new THREE.MeshStandardMaterial({color:0xe5c185,emissive:0xe5a554,emissiveIntensity:night?.65:0,roughness:.6}),lit)
    if(detailed) {
      instances(group,new THREE.BoxGeometry(1.15,.12,.4),surface(0xddd8c5),ledges)
      instances(group,new THREE.BoxGeometry(.55,.4,.38),surface(0xaab3b0),ac)
      box(group,[width*.35,1.5,depth*.38],[0,height+.9,0],0x939c91)
      for(const x of [-width/2+.25,width/2-.25]) box(group,[.08,height,.1],[x,height/2,depth/2+.1],0x647872)
      for(const side of [-1,1]) {
        box(group,[1.6,2.5,.14],[0,1.25,side*(depth/2+.08)],0x254e4c)
        box(group,[2.8,.15,1.5],[0,2.65,side*(depth/2+.55)],0x798a80)
        box(group,[2.4,.16,.9],[0,.09,side*(depth/2+.45)],0xa8aaa0)
      }
    }
    // Both levels retain windows. Only small fixtures disappear in overview.
    lod.addLevel(group,detailed?0:90, .12)
  }
  return lod
}

export function createChargingShed(width: number, depth: number) {
  const group = new THREE.Group()
  box(group,[width+.5,.15,depth+.5],[0,.08,0],0x9ba396)
  box(group,[width+.8,.2,depth+.65],[0,2.75,0],0x577d77)
  for(const x of [-width/2+.2,width/2-.2]) for(const z of [-depth/2+.2,depth/2-.2]) box(group,[.12,2.7,.12],[x,1.4,z],0x748a83)
  const count=Math.max(2,Math.floor(width/1.3))
  for(let i=0;i<count;i++) {
    const x=(i-(count-1)/2)*(width/(count+1))
    box(group,[.32,.65,.16],[x,1.2,-depth/2+.2],0xeee6cf)
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
  return group
}

/** Physical pavement stays stable while the separate risk layer changes. */
export function createStreet(length: number, width: number) {
  const group = new THREE.Group()
  box(group,[width,.1,length],[0,.02,0],0x505a57)
  for(const side of [-1,1]) box(group,[.3,.17,length],[side*(width/2+.18),.1,0],0xa4aca0)
  const marks: Array<[number,number,number,number]>=[]
  for(let z=-length/2+1.5;z<length/2-1;z+=3.5) marks.push([0,.09,z,0])
  instances(group,new THREE.BoxGeometry(.09,.02,1.5),surface(0xd8d3b5),marks)
  return group
}
