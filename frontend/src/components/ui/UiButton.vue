<script setup lang="ts">
withDefaults(defineProps<{
  type?: 'button' | 'submit' | 'reset'
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'sm' | 'md'
  loading?: boolean
  disabled?: boolean
  block?: boolean
}>(), { type: 'button', variant: 'secondary', size: 'md', loading: false, disabled: false, block: false })
</script>

<template>
  <button :type="type" class="ui-button" :class="[`ui-button--${variant}`, `ui-button--${size}`, { 'ui-button--block': block }]" :disabled="disabled || loading" :aria-busy="loading">
    <span v-if="loading" class="ui-button__spinner" aria-hidden="true"></span><slot />
  </button>
</template>
