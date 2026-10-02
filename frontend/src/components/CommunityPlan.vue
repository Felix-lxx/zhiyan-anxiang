<script setup lang="ts">
import { computed } from 'vue'
import type { Simulation } from '../domain/drill'
const props = defineProps<{ simulation: Simulation; target?: { x:number; y:number }; route?: Array<{x:number;y:number}> }>()
const world = computed(() => (props.simulation as Simulation & { world?: { objects: Array<{id:string;name:string;type:string;x:number;y:number;width:number;depth:number}>;fire_origin?: {x:number;y:number} } }).world)
const points = computed(() => props.route?.map(p=>`${p.x},${p.y}`).join(' ') || '')
</script>
<template>
  <svg class="community-plan" viewBox="0 0 100 100" role="img" aria-label="当前场景平面图与任务位置">
    <rect width="100" height="100" fill="#172c29" />
    <g v-for="edge in simulation.road_network?.edges" :key="edge.id"><line :x1="edge.start.x" :y1="edge.start.y" :x2="edge.end.x" :y2="edge.end.y" :stroke="edge.status==='blocked'?'#bd542e':edge.status==='restricted'?'#937839':'#455954'" :stroke-width="Math.max(1,edge.width_meters*.45)" stroke-linecap="round" /></g>
    <g v-for="o in world?.objects.filter(o=>o.type==='building'||o.type==='charging_shed')" :key="o.id"><rect :x="o.x-o.width/2" :y="o.y-o.depth/2" :width="Math.max(3,o.width)" :height="Math.max(3,o.depth)" rx=".4" fill="#687872" stroke="#90a295" stroke-width=".3"/><text :x="o.x" :y="o.y" text-anchor="middle" fill="#eef0e5" font-size="2.3">{{o.name}}</text></g>
    <circle v-if="world?.fire_origin" :cx="world.fire_origin.x" :cy="world.fire_origin.y" :r="Math.min(18,simulation.fire.smoke_radius*.6)" fill="#d65f2845" stroke="#d97442" stroke-width=".4" />
    <g v-for="n in simulation.road_network?.nodes.filter(n=>n.is_exit)" :key="n.id"><circle :cx="n.x" :cy="n.y" r="1.4" fill="#69dfa4"/><text :x="n.x" :y="n.y-2" fill="#b6ebcf" text-anchor="middle" font-size="2.4">{{n.name}}</text></g>
    <polyline v-if="points" :points="points" fill="none" stroke="#72efac" stroke-width="1.2" stroke-dasharray="2 1.5" stroke-linecap="round"/>
    <g v-if="target"><circle :cx="target.x" :cy="target.y" r="2.2" fill="#ec9565" stroke="#fff0d5" stroke-width=".8"/><text :x="target.x" :y="target.y-4" text-anchor="middle" fill="#fff4e5" font-size="3">任务目标</text></g>
    <g v-for="p in simulation.residents" :key="p.id"><circle :cx="p.x" :cy="p.y" r=".35" :fill="p.status==='evacuated'?'#70d7a8':p.vulnerable?'#eccb76':'#c5d7d0'" /></g>
  </svg>
</template>
<style scoped>.community-plan{display:block;width:100%;height:100%;min-height:220px;background:#172c29}</style>
