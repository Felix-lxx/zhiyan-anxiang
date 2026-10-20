import * as THREE from 'three'

/** Direction marks lie on confirmed segments, never on a shortcut across corners. */
export function createRouteGuide(points:THREE.Vector3[], color:number, robot=false):THREE.Group {
  const group=new THREE.Group()
  const path=points.filter((point,index)=>index===0||point.distanceToSquared(points[index-1]!)>.000001)
  if(path.length<2)return group
  const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints(path),new THREE.LineDashedMaterial({
    color,dashSize:robot?1.4:.9,gapSize:.45,transparent:true,opacity:.9,
  }))
  line.computeLineDistances();group.add(line)
  const lengths=path.slice(1).map((point,index)=>point.distanceTo(path[index]!))
  const total=lengths.reduce((sum,length)=>sum+length,0)
  const count=Math.min(6,Math.max(1,Math.floor(total/8))), vertices:THREE.Vector3[]=[]
  let start=0, marker=1
  for(let index=0;index<lengths.length&&marker<=count;index++) {
    const length=lengths[index]!, a=path[index]!, b=path[index+1]!
    while(marker<=count&&total*marker/(count+1)<=start+length) {
      const distance=total*marker/(count+1)-start;marker++
      const direction=b.clone().sub(a).normalize()
      const side=new THREE.Vector3(-direction.z,0,direction.x)
      if(side.lengthSq()<.000001||distance<.08)continue
      side.normalize()
      const tip=a.clone().addScaledVector(direction,distance)
      const back=Math.min(robot ? .8 : .6,distance*.7)
      const base=tip.clone().addScaledVector(direction,-back)
      vertices.push(tip,base.clone().addScaledVector(side,back*.45),tip.clone(),base.clone().addScaledVector(side,-back*.45))
    }
    start+=length
  }
  if(vertices.length) {
    const arrows=new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(vertices),new THREE.LineBasicMaterial({color,transparent:true,opacity:.95}))
    arrows.name='route-direction-marks';group.add(arrows)
  }
  return group
}
