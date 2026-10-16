import { onBeforeUnmount, shallowRef, ref, watch } from 'vue'

/** One cancellable read-only preview, scoped to a live drill. Never abort a submitted command. */
export function useDrillPreview<T>(scope: () => string, enabled: () => boolean) {
  const data = shallowRef<T | null>(null), pending = ref(false)
  let generation = 0, controller: AbortController | null = null
  function cancel() {
    generation++; controller?.abort(); controller = null
    data.value = null; pending.value = false
  }
  async function run(load: (signal: AbortSignal) => Promise<T>): Promise<T | undefined> {
    cancel()
    if (!scope() || !enabled()) return
    const id = generation, key = scope(), request = new AbortController()
    controller = request; pending.value = true
    const timeout = setTimeout(() => request.abort(new DOMException('预演超时', 'TimeoutError')), 15000)
    try {
      const value = await load(request.signal)
      if (id !== generation || scope() !== key || !enabled()) return
      data.value = value
      return value
    } catch (cause) {
      if (id !== generation || scope() !== key || !enabled()) return
      if (request.signal.aborted) throw new Error('路线预演超时，尚未下达指令。请重新选择目标后重试。')
      throw cause
    } finally { clearTimeout(timeout); if (id === generation) { pending.value = false; controller = null } }
  }
  watch([scope, enabled], cancel, { flush: 'sync' })
  onBeforeUnmount(cancel)
  return { data, pending, run, cancel }
}
