<script setup lang="ts">
import AppIcon from '../AppIcon.vue'

withDefaults(defineProps<{
  label: string
  icon: string
  pressed?: boolean
  disabled?: boolean
  size?: number
}>(), { pressed: false, disabled: false, size: 19 })
</script>

<template>
  <button type="button" class="ui-icon-button" :aria-label="label" :title="label" :aria-pressed="pressed" :disabled="disabled"><AppIcon :name="icon" :size="size" /><slot /></button>
</template>
