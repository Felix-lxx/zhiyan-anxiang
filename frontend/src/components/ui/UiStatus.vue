<script setup lang="ts">
withDefaults(defineProps<{ tone?: 'neutral' | 'success' | 'warning' | 'danger'; live?: boolean }>(), { tone: 'neutral', live: false })
</script>

<template>
  <span class="ui-status" :data-tone="tone" :role="live ? 'status' : undefined" :aria-live="live ? 'polite' : undefined"><slot /></span>
</template>
