<script setup lang="ts">
import { useId } from 'vue'

defineProps<{
  modelValue: string
  label: string
  options: Array<{ value: string; label: string; disabled?: boolean }>
  hint?: string
  disabled?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: string]; change: [event: Event] }>()
const id = useId()
function update(event: Event) { emit('update:modelValue', (event.target as HTMLSelectElement).value); emit('change', event) }
</script>

<template>
  <label class="ui-field" :for="id"><span class="ui-field__label">{{ label }}</span><select :id="id" :value="modelValue" :disabled="disabled" @change="update"><option v-for="option in options" :key="option.value" :value="option.value" :disabled="option.disabled">{{ option.label }}</option></select><small v-if="hint" class="ui-field__hint">{{ hint }}</small></label>
</template>
