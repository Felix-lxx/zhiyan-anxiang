export interface VersionedState { id: string; state_version?: string; latest_event_sequence?: number }
export type ConnectionState = 'connecting' | 'live' | 'stale'
export interface StatePatch { path: string[]; value?: unknown; remove?: boolean }
export type LiveMessage<T> =
  | { type: 'drill.snapshot'; data: T }
  | { type: 'drill.delta'; drill_id: string; base_version: string; state_version: string; patch: StatePatch[] }
  | { type: 'drill.heartbeat'; drill_id: string; state_version: string }
  | { type: 'drill.catchup'; drill_id: string; after_sequence: number; latest_sequence: number; complete: boolean; events: Array<{ sequence: number }> }

export function isNewerState(candidate: VersionedState, current: VersionedState | null): boolean {
  if (!current || candidate.id !== current.id) return true
  if (!candidate.state_version) return !current.state_version
  if (!current.state_version) return true
  const next = candidate.state_version.split(':').map(Number)
  const old = current.state_version.split(':').map(Number)
  for (let index = 0; index < 2; index += 1) {
    const nextPart = next[index] ?? 0
    const oldPart = old[index] ?? 0
    if (nextPart !== oldPart) return nextPart > oldPart
  }
  // Presence is an independently versioned live projection; ordered socket delivery
  // makes any differing presence revision authoritative for the same simulation tick.
  return true
}

export function applyLiveMessage<T extends VersionedState>(previous: T | null, message: LiveMessage<T>): T | null {
  if (message.type === 'drill.catchup') return previous
  if (message.type === 'drill.snapshot') return message.data
  if (!previous || message.drill_id !== previous.id) throw new Error('现场连接已切换，正在重新同步。')
  if (message.type === 'drill.heartbeat') {
    if (message.state_version !== previous.state_version) throw new Error('现场版本已更新，正在补齐状态。')
    return previous
  }
  if (previous.state_version !== message.base_version) throw new Error('现场更新不连续，正在重新同步。')
  const next = { ...previous } as T & Record<string, unknown>
  for (const change of message.patch) {
    if (!change.path.length || change.path.some(key => ['__proto__', 'prototype', 'constructor'].includes(key))) throw new Error('无效现场更新')
    let target: Record<string, unknown> = next
    for (const key of change.path.slice(0, -1)) {
      const child = target[key]
      if (!child || typeof child !== 'object' || Array.isArray(child)) throw new Error('现场更新路径已变化')
      target[key] = { ...child }
      target = target[key] as Record<string, unknown>
    }
    const key = change.path[change.path.length - 1]!
    if (change.remove) delete target[key]
    else target[key] = change.value
  }
  if (next.state_version !== message.state_version) throw new Error('现场版本校验失败')
  return next
}

/** Keep transport state apart from HTTP results; an old delta cannot undo a command. */
export function connectLive<T extends VersionedState>(options: {
  url: string; drillId: string; onState: (state: T) => void
  onStatus: (state: ConnectionState) => void; onError?: (message: string) => void
  onRecovered?: (count: number, complete: boolean) => void
}): () => void {
  let socket: WebSocket | null = null, stopped = false, attempt = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let stream: T | null = null, lastMessageAt = Date.now(), lastSequence: number | null = null
  function open() {
    if (stopped) return
    options.onStatus(attempt ? 'stale' : 'connecting')
    stream = null
    const cursor = lastSequence === null ? '' : `&after_sequence=${lastSequence}`
    const current = new WebSocket(options.url + '&protocol=2' + cursor)
    socket = current; lastMessageAt = Date.now()
    current.onmessage = event => {
      if (stopped || socket !== current) return
      try {
        const message = JSON.parse(event.data) as LiveMessage<T>
        if (!['drill.snapshot', 'drill.delta', 'drill.heartbeat', 'drill.catchup'].includes(message.type)) return
        if (message.type === 'drill.catchup') {
          lastMessageAt = Date.now()
          options.onRecovered?.(message.events.length, message.complete)
          return
        }
        stream = applyLiveMessage(stream, message)
        if (stream?.id !== options.drillId) throw new Error('场次不一致')
        if (typeof stream.latest_event_sequence === 'number') lastSequence = stream.latest_event_sequence
        lastMessageAt = Date.now(); attempt = 0; options.onStatus('live')
        if (message.type !== 'drill.heartbeat') options.onState(stream)
      } catch { options.onStatus('stale'); current.close(4000, 'resync') }
    }
    current.onerror = () => { if (!stopped && socket === current) options.onStatus('stale') }
    current.onclose = event => {
      if (stopped || socket !== current) return
      options.onStatus('stale')
      if ([4401, 4404].includes(event.code)) { options.onError?.('当前场次连接已失效，请返回重新进入。'); return }
      timer = setTimeout(open, Math.min(1000 * 2 ** attempt++, 10000))
    }
  }
  open()
  const watchdog = setInterval(() => {
    if (!stopped && socket && socket.readyState < WebSocket.CLOSING && Date.now() - lastMessageAt > 12000) {
      options.onStatus('stale'); socket.close(4000, 'heartbeat timeout')
    }
  }, 4000)
  return () => { stopped = true; clearTimeout(timer); clearInterval(watchdog); socket?.close() }
}
