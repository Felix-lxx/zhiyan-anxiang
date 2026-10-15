<script setup lang="ts">
import { nextTick, onActivated, onBeforeUnmount, onMounted, ref } from 'vue'
import UiIconButton from './UiIconButton.vue'

defineProps<{ title: string; subtitle?: string; section?: string }>()
const emit = defineEmits<{ close: [] }>()
const closeButton = ref<InstanceType<typeof UiIconButton> | null>(null)
let previousFocus: HTMLElement | null = null
function focusDrawer() {
  previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  void nextTick(() => {
    const button = closeButton.value?.$el as HTMLButtonElement | undefined
    if (button?.getClientRects().length && !button.closest('[inert]')) button.focus({ preventScroll: true })
  })
}
onMounted(focusDrawer)
onActivated(focusDrawer)
onBeforeUnmount(() => {
  const button = closeButton.value?.$el as HTMLButtonElement | undefined
  if (button?.closest('.ui-drawer')?.contains(document.activeElement) && previousFocus?.getClientRects().length) previousFocus.focus({ preventScroll: true })
})
</script>

<template>
  <section class="ui-drawer" role="dialog" aria-modal="false" :aria-label="title" @keydown.esc.stop="emit('close')">
    <header class="ui-drawer__header"><div><h2>{{ title }}</h2><p v-if="subtitle">{{ subtitle }}</p></div><UiIconButton ref="closeButton" label="关闭面板" icon="close" @click="emit('close')" /></header>
    <slot :section="section" />
  </section>
</template>
