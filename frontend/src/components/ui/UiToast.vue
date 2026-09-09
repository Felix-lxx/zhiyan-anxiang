<script setup lang="ts">
import AppIcon from '../AppIcon.vue'
import UiButton from './UiButton.vue'
import UiIconButton from './UiIconButton.vue'

withDefaults(defineProps<{ message: string; tone?: 'neutral' | 'success' | 'warning' | 'danger'; actionLabel?: string; dismissible?: boolean }>(), { tone: 'neutral', actionLabel: '', dismissible: true })
const emit = defineEmits<{ action: []; dismiss: [] }>()
</script>

<template>
  <aside class="ui-toast" :data-tone="tone" :role="tone === 'danger' ? 'alert' : 'status'" :aria-live="tone === 'danger' ? 'assertive' : 'polite'"><AppIcon class="ui-toast__icon" :name="tone === 'danger' ? 'pulse' : tone === 'success' ? 'check' : 'help'" /><p>{{ message }}</p><div class="ui-toast__actions"><UiButton v-if="actionLabel" size="sm" variant="ghost" @click="emit('action')">{{ actionLabel }}</UiButton><UiIconButton v-if="dismissible" label="关闭提示" icon="close" @click="emit('dismiss')" /></div></aside>
</template>
