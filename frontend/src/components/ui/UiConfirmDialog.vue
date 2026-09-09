<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import UiButton from './UiButton.vue'

const props = withDefaults(defineProps<{
  open: boolean
  title: string
  description: string
  confirmLabel?: string
  cancelLabel?: string
  busy?: boolean
  danger?: boolean
  theme?: 'light' | 'immersive'
}>(), { confirmLabel: '确认', cancelLabel: '取消', busy: false, danger: false, theme: 'light' })
const emit = defineEmits<{ confirm: []; cancel: [] }>()
const panel = ref<HTMLElement | null>(null)
const confirmButton = ref<InstanceType<typeof UiButton> | null>(null)
let previousFocus: HTMLElement | null = null
watch(() => props.open, open => {
  if (open) { previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null; void nextTick(() => (confirmButton.value?.$el as HTMLButtonElement | undefined)?.focus({ preventScroll: true })) }
  else { previousFocus?.focus({ preventScroll: true }); previousFocus = null }
})
onBeforeUnmount(() => previousFocus?.focus({ preventScroll: true }))
function trapFocus(event: KeyboardEvent) {
  if (event.key === 'Escape' && !props.busy) { emit('cancel'); return }
  if (event.key !== 'Tab') return
  const items = [...(panel.value?.querySelectorAll<HTMLElement>('button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]') ?? [])]
  const first = items[0], last = items[items.length - 1]
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
</script>

<template>
  <Teleport to="body"><div v-if="open" class="ui-dialog-backdrop" :data-ui-theme="theme === 'immersive' ? 'immersive' : undefined" @keydown="trapFocus"><section ref="panel" class="ui-dialog" role="alertdialog" aria-modal="true" aria-labelledby="ui-confirm-title" aria-describedby="ui-confirm-description"><h2 id="ui-confirm-title">{{ title }}</h2><p id="ui-confirm-description">{{ description }}</p><div class="ui-dialog__actions"><UiButton variant="ghost" :disabled="busy" @click="emit('cancel')">{{ cancelLabel }}</UiButton><UiButton ref="confirmButton" :variant="danger ? 'danger' : 'primary'" :loading="busy" @click="emit('confirm')">{{ confirmLabel }}</UiButton></div></section></div></Teleport>
</template>
