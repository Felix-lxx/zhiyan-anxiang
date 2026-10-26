// Deliberately isolated layout data, not an alternative simulation engine.
export const kitchenCapabilities={code:'kitchen_fire',contract_version:1,title:'住宅厨房火灾',status:'available',notice:'选择楼栋、楼层与厨房，观察分区烟气与连续疏散。',source_types:['kitchen'],location_kinds:['room'],features:['房间选点','分区烟气','室内处置与复盘'],can_create:true,can_configure:true,can_preview:true,can_publish:true,can_run:true}
export const kitchenDefaults={fire_source_type:'kitchen',fire_source_object_id:'home',fire_floor:2,fire_room:'east',room_door_state:'open',start_time:'18:30',wind_direction:'微风',resident_count:8,hydrant_status:'available',south_lane_status:'open',stair_width:1.2}
export function kitchenPreview(parameters=kitchenDefaults){
  const nodes=[],edges=[],zones=[],doors=[]
  nodes.push({id:'stair-0',name:'首层楼梯出口',x:45.2,y:50,height:0,floor:0,kind:'stairs',building_id:'home'})
  for(let floor=1;floor<=4;floor++){
    const hall={id:'hall-'+floor,name:floor+'层走廊',x:50,y:50,height:(floor-1)*3.2+.18,floor,kind:'corridor',building_id:'home'}
    const stair={...hall,id:'stair-'+floor,name:floor+'层楼梯',x:45.2,y:50+(floor%2?2:-2),kind:'stairs'}
    nodes.push(hall,stair);zones.push({...hall,width:11,depth:1.6,smoke_density:floor===parameters.fire_floor?.15:.01,temperature:30,visibility:85},{...stair,width:2,depth:6,smoke_density:.02,temperature:25,visibility:98})
    for(const room of ['east','west']){
      const node={...hall,id:`indoor:home:${floor}:${room}`,name:`示例楼 · ${floor}层${room==='east'?'东':'西'}侧厨房`,x:room==='east'?54.9:48.9,y:47.5,kind:'room'}
      const portal={...hall,id:node.id+':entry',name:'厨房门前走廊',x:node.x}
      nodes.push(node,portal);zones.push({...node,width:5.8,depth:4,smoke_density:floor===parameters.fire_floor&&room===parameters.fire_room?.5:.01,temperature:45,visibility:50},{...portal,width:.9,depth:1,smoke_density:.01,temperature:25,visibility:99})
      const edge={id:'door-'+floor+'-'+room,name:'房门',kind:'room',start_node_id:node.id,end_node_id:portal.id,start:node,end:portal,width_meters:.9,status:'open'};edges.push(edge)
      edges.push({id:node.id+':corridor',name:'走廊',kind:'corridor',start_node_id:portal.id,end_node_id:hall.id,start:portal,end:hall,width_meters:1.5,status:'open'})
      doors.push({id:edge.id,label:node.name+'房门',floor,room_id:node.id,
        portal:{x:node.x,y:node.y+2,height:node.height,width:.9,normal_x:0,normal_y:1,clearance_radius:.28,wall_depth:.1},
        state:floor===parameters.fire_floor&&room===parameters.fire_room?parameters.room_door_state:'open'})
    }
    edges.push({id:'hall-edge-'+floor,kind:'corridor',name:'走廊',start:hall,end:stair,start_node_id:hall.id,end_node_id:stair.id,width_meters:1.5,status:'open'})
    const below=nodes.find(node=>node.id==='stair-'+(floor-1))
    edges.push({id:'stairs-'+floor,kind:'stairs',name:'楼梯',start:stair,end:below,start_node_id:stair.id,end_node_id:below.id,width_meters:1.2,status:'open'})
  }
  const source=nodes.find(node=>node.id===`indoor:home:${parameters.fire_floor}:${parameters.fire_room}`)
  const equipment_layouts=zones.filter(zone=>zone.kind==='room').map(zone=>{
    const counter={x:zone.x,y:zone.y-zone.depth*.38,width:zone.width*.82,depth:zone.depth*.2}
    const position={x:counter.x+counter.width*.375,y:counter.y,height:zone.height}
    return {room_id:zone.id,counter,gas_valve:{id:zone.id+':gas-valve',kind:'gas_valve',label:zone.name+'燃气阀',room_id:zone.id,floor:zone.floor,position:{x:position.x-counter.width/10,y:position.y,height:zone.height+1.35},approach_node_id:zone.id,approach_position:{x:zone.x,y:zone.y,height:zone.height}},stove:{id:zone.id+':stove',kind:'stove',room_id:zone.id,label:zone.name+'灶台',floor:zone.floor,position,width:counter.width/4-.04,depth:counter.depth,height:.92,ignition_position:{...position,height:zone.height+.92},approach_node_id:zone.id,approach_position:{x:zone.x,y:zone.y,height:zone.height}}}
  })
  const stove=equipment_layouts.find(item=>item.room_id===source.id).stove
  const indoor={building_id:'home',source_zone_id:source.id,source_label:source.name,zones,doors,equipment_layout_version:1,equipment_layouts,devices:equipment_layouts.map(item=>({id:item.gas_valve.id,room_id:item.room_id,state:'open',basis:'initial'}))}
  return {minute:0,fire_level:'初起',smoke_level:'分区发展',risk_level:'关注',route_advice:'查看房门状态并组织居民下楼，燃气任务需核验处置证据。',explanation:'隔离布局验收数据，不连接用户社区。',affected_targets:[source.name],simulation:{
    world:{schema_version:3,spatial_units:{height_mode:'meters'},parameters,fire_source:{location:{object_id:'home'},device_id:stove.id,ignition_position:stove.ignition_position},fire_origin:source,objects:[{id:'home',name:'示例住宅楼',type:'building',x:50,y:50,width:16,depth:10,floors:4,entry:{x:50,y:58}}]},
    spatial_network:{nodes,edges,stair_width:1.2},road_network:{nodes:[],edges:[]},environment:{indoor,east_hydrant:'available',south_lane:'open',visibility:50},
    fire:{intensity:25,smoke_radius:8,temperature:120},sensors:{temperature:120,smoke_ppm:300,alarm:true},residents:[],helpers:[],vehicles:[],summary:{total:0,evacuated:0,moving:0,vulnerable:0,missing:0},
  }}
}
