<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import UiIconButton from './UiIconButton.vue'

defineProps<{ title: string; subtitle?: string }>()
const emit = defineEmits<{ close: [] }>()
const closeButton = ref<InstanceType<typeof UiIconButton> | null>(null)
const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
onMounted(() => void nextTick(() => (closeButton.value?.$el as HTMLButtonElement | undefined)?.focus({ preventScroll: true })))
onBeforeUnmount(() => previousFocus?.focus({ preventScroll: true }))
</script>

<template>
  <section class="ui-drawer" role="dialog" aria-modal="false" :aria-label="title" @keydown.esc.stop="emit('close')">
    <header class="ui-drawer__header"><div><h2>{{ title }}</h2><p v-if="subtitle">{{ subtitle }}</p></div><UiIconButton ref="closeButton" label="关闭面板" icon="close" @click="emit('close')" /></header>
    <slot />
  </section>
</template>
