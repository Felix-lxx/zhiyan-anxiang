<script setup lang="ts">
const props = withDefaults(defineProps<{ name: string; size?: number; strokeWidth?: number }>(), { size: 20, strokeWidth: 1.8 })

const paths: Record<string, string[]> = {
  send: ['m3 3 18 9-18 9 4-9-4-9Zm4 9h14'],
  refresh: ['M20 7v5h-5M4 17v-5h5', 'M5 7a8 8 0 0 1 13-2l2 3M4 16l2 3a8 8 0 0 0 13-2'],
  arrowRight: ['M4 12h16m-6-6 6 6-6 6'],
  plus: ['M12 5v14M5 12h14'],
  search: ['M10.5 3a7.5 7.5 0 1 0 0 15 7.5 7.5 0 0 0 0-15Z', 'm16 16 5 5'],
  building: ['M5 21V3h10v18M15 9h5v12M3 21h19M8 7h4M8 11h4M8 15h4M9 21v-3h2v3'],
  lock: ['M6 10h12v11H6Z', 'M8 10V6a4 4 0 0 1 8 0v4M12 14v3'],
  eyeOff: ['M3 3l18 18M10 5a12 12 0 0 1 12 7s-1 2-3 4M6 6a17 17 0 0 0-4 6s4 7 10 7c2 0 4-1 5-2M10 10a3 3 0 0 0 4 4'],
  logout: ['M9 3H4v18h5M10 12h11m-4-4 4 4-4 4'],
  back: ['M19 12H5m6-6-6 6 6 6'],
  play: ['M8 5v14l11-7Z'],
  pause: ['M8 5v14M16 5v14'],
  stop: ['M7 7h10v10H7Z'],
  tasks: ['M9 6h11M9 12h11M9 18h11', 'm4 6 1 1 2-2m-3 7 1 1 2-2m-3 7 1 1 2-2'],
  pulse: ['M3 12h4l2.2-6 4.1 12 2.2-6H21'],
  split: ['M5 5h4a3 3 0 0 1 3 3v8a3 3 0 0 0 3 3h4', 'm16 16 3 3-3 3M12 12h4a3 3 0 0 0 3-3V5', 'm16 2 3 3-3 3'],
  swap: ['M7 7h11m0 0-3-3m3 3-3 3', 'M17 17H6m0 0 3 3m-3-3 3-3'],
  compare: ['M4 5h6v14H4Z', 'M14 9h6v10h-6Z', 'M3 19h18'],
  phone: ['M8 2h8a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2Z', 'M10 5h4m-3 14h2'],
  brain: ['M9.5 4.5A3.5 3.5 0 0 0 6 8v.5A3.5 3.5 0 0 0 4 15a3.5 3.5 0 0 0 5.5 3V4.5Zm5 0A3.5 3.5 0 0 1 18 8v.5a3.5 3.5 0 0 1 2 6.5 3.5 3.5 0 0 1-5.5 3V4.5Z', 'M9.5 9H7m7.5 3H18M9.5 15H7m7.5-7h2'],
  volume: ['M5 9v6h4l5 4V5L9 9H5Z', 'M17 9a4 4 0 0 1 0 6m2-8a7 7 0 0 1 0 10'],
  volumeOff: ['M5 9v6h4l5 4V5L9 9H5Z', 'm18 9 4 6m0-6-4 6'],
  camera: ['M4 7h4l2-3h4l2 3h4a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2Z', 'M12 10a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z'],
  award: ['M12 3a6 6 0 1 0 0 12 6 6 0 0 0 0-12Z', 'm8 14-2 7 6-3 6 3-2-7'],
  inspect: ['M10.5 18a7.5 7.5 0 1 1 5.3-2.2L21 21', 'M10.5 7v7m-3.5-3.5h7'],
  block: ['M5 7h14v10H5Z', 'M8 7l3 10m2-10 3 10M3 5h18M3 19h18'],
  robot: ['M7 8h10a3 3 0 0 1 3 3v7H4v-7a3 3 0 0 1 3-3Z', 'M12 8V4m-3 9h.01M15 13h.01M8 18v3m8-3v3'],
  users: ['M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm6-1a3 3 0 1 0 0-6', 'M2 21a7 7 0 0 1 14 0m1-7a5 5 0 0 1 5 5v2'],
  fire: ['M13 2s1 4-2 6c-2-3-6 1-6 6a7 7 0 0 0 14 0c0-5-3-7-3-7s0 4-3 5c1-5 0-10 0-10Z'],
  water: ['M12 2S5 10 5 15a7 7 0 0 0 14 0c0-5-7-13-7-13Z', 'M9 16a3 3 0 0 0 3 3'],
  person: ['M12 3a3 3 0 1 0 0 6 3 3 0 0 0 0-6Zm-5 18v-5a5 5 0 0 1 10 0v5'],
  eye: ['M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z', 'M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z'],
  route: ['M5 19a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm14-14a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z', 'M7 19h3a4 4 0 0 0 4-4V9a4 4 0 0 1 4-4'],
  close: ['M5 5l14 14M19 5 5 19'],
  help: ['M9.5 9a3 3 0 1 1 4.8 2.4c-1.7 1.1-2.3 1.8-2.3 3.1', 'M12 19h.01', 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Z'],
  clock: ['M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Z', 'M12 6v6l4 2'],
  target: ['M12 2v4m0 12v4M2 12h4m12 0h4', 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z'],
  chevron: ['m8 10 4 4 4-4'],
  check: ['m5 12 4 4L19 6'],
  broadcast: ['M5 10v4l11 4V6L5 10Zm0 4-2 2v-8l2 2m5 6 1 5'],
  compass: ['M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Z', 'm15 9-2 4-4 2 2-4 4-2Z'],
  rescue: ['M12 3v18M3 12h18', 'M6 6h12v12H6Z'],
  more: ['M5 12h.01M12 12h.01M19 12h.01'],
  settings: ['M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z', 'M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.12 3.67-.08-.02a1.7 1.7 0 0 0-1.8.31 1.7 1.7 0 0 0-.6 1.1h-4.4a1.7 1.7 0 0 0-.6-1.1 1.7 1.7 0 0 0-1.8-.31l-.08.02-2.12-3.67.06-.06A1.7 1.7 0 0 0 6.6 15a1.7 1.7 0 0 0-1.4-1.22H5v-4.24h.2A1.7 1.7 0 0 0 6.6 8.32a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.12-3.67.08.02a1.7 1.7 0 0 0 1.8-.31A1.7 1.7 0 0 0 10.8 1h4.4a1.7 1.7 0 0 0 .6 1.42 1.7 1.7 0 0 0 1.8.31l.08-.02 2.12 3.67-.06.06a1.7 1.7 0 0 0-.34 1.88 1.7 1.7 0 0 0 1.4 1.22h.2v4.24h-.2A1.7 1.7 0 0 0 19.4 15Z'],
}
</script>

<template>
  <svg :width="props.size" :height="props.size" viewBox="0 0 24 24" fill="none" stroke="currentColor" :stroke-width="props.strokeWidth" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
    <path v-for="path in paths[props.name] ?? paths.help" :key="path" :d="path" />
  </svg>
</template>
