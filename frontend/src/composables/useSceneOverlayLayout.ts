import { ref, watch } from 'vue'

/** Keep scene panels below the rendered toolbar, including zoom and wrapped controls. */
export function useSceneOverlayLayout() {
  const utilities = ref<HTMLElement | null>(null)
  watch(utilities, (element, _, cleanup) => {
    const stage = element?.closest<HTMLElement>('.director-stage')
    const director = stage?.closest<HTMLElement>('.operations-center--immersive')
    if (!element || !stage || !director) return
    const measure = () => {
      if (!element.getClientRects().length) return
      const bottom = Math.ceil(element.getBoundingClientRect().bottom - stage.getBoundingClientRect().top) + 12
      director.style.setProperty('--scene-panel-top', `${bottom}px`)
    }
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    observer.observe(stage)
    measure()
    cleanup(() => { observer.disconnect(); director.style.removeProperty('--scene-panel-top') })
  }, { flush: 'post' })
  return utilities
}
