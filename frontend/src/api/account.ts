import { ref } from 'vue'
import type { AccountProfile } from '../domain/account'

export const accountProfile = ref<AccountProfile | null>(null)
export function applyAccountProfile(profile: AccountProfile | null) {
  accountProfile.value = profile
  document.documentElement.dataset.readingSize = profile?.text_size ?? 'comfortable'
  document.documentElement.dataset.reduceMotion = String(profile?.reduced_motion ?? false)
}
