import type { AgentLiveState } from '../domain/agent'

export interface VersionedState { id: string; state_version?: string; latest_event_sequence?: number }
export type ConnectionState = 'connecting' | 'live' | 'stale'
interface EntityDelta { added: Array<Record<string, unknown> & { id: string }>; removed: string[]; updated: Array<{ id: string; set: Record<string, unknown>; unset: string[] }>; order?: string[] }
export interface StatePatch { path: string[]; value?: unknown; remove?: boolean; entities?: EntityDelta }
const unsafeKey = (key: string) => ['__proto__', 'prototype', 'constructor'].includes(key)
function patchEntities(source: unknown, delta: EntityDelta): unknown[] {
  if (!Array.isArray(source)) throw new Error('实体列表已变化')
  const items = new Map<string, Record<string, unknown>>()
  for (const item of source) {
    if (!item || typeof item.id !== 'string' || items.has(item.id)) throw new Error('实体编号不唯一')
    items.set(item.id, item)
  }
  for (const id of delta.removed) { if (!items.delete(id)) throw new Error('待移除实体不存在') }
  for (const update of delta.updated) {
    const item = items.get(update.id)
    if (!item || Object.keys(update.set).some(key => unsafeKey(key) || key === 'id') || update.unset.some(key => unsafeKey(key) || key === 'id')) throw new Error('实体更新无效')
    const next = { ...item, ...update.set }
    for (const key of update.unset) delete next[key]
    items.set(update.id, next)
  }
  for (const item of delta.added) {
    if (!item || typeof item.id !== 'string' || items.has(item.id) || Object.keys(item).some(unsafeKey)) throw new Error('新增实体无效')
    items.set(item.id, item)
  }
  if (delta.order) {
    if (delta.order.length !== items.size || new Set(delta.order).size !== items.size || delta.order.some(id => !items.has(id))) throw new Error('实体顺序不连续')
    return delta.order.map(id => items.get(id)!)
  }
  return [...items.values()]
}
export type LiveMessage<T> =
  | { type: 'drill.snapshot'; data: T }
  | { type: 'drill.delta'; drill_id: string; base_version: string; state_version: string; patch: StatePatch[] }
  | { type: 'drill.heartbeat'; drill_id: string; state_version: string }
  | { type: 'drill.catchup'; drill_id: string; after_sequence: number; latest_sequence: number; complete: boolean; events: Array<{ sequence: number }> }

export type AgentLiveMessage =
  | { type:'agent.snapshot';data:AgentLiveState }
  | { type:'agent.delta';drill_id:string;base_version:string;state_version:string;patch:StatePatch[] }

export function applyAgentMessage(previous:AgentLiveState|null, message:AgentLiveMessage):AgentLiveState|null {
  return message.type==='agent.snapshot'
    ? applyLiveMessage(previous,{type:'drill.snapshot',data:message.data})
    : applyLiveMessage(previous,{...message,type:'drill.delta'})
}

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
    if (!change.path.length || change.path.some(unsafeKey)) throw new Error('无效现场更新')
    let target: Record<string, unknown> = next
    for (const key of change.path.slice(0, -1)) {
      const child = target[key]
      if (!child || typeof child !== 'object' || Array.isArray(child)) throw new Error('现场更新路径已变化')
      target[key] = { ...child }
      target = target[key] as Record<string, unknown>
    }
    const key = change.path[change.path.length - 1]!
    if (change.entities) target[key] = patchEntities(target[key], change.entities)
    else if (change.remove) delete target[key]
    else target[key] = change.value
  }
  if (next.state_version !== message.state_version) throw new Error('现场版本校验失败')
  return next
}

/** Keep transport state apart from HTTP results; an old delta cannot undo a command. */
export function connectLive<T extends VersionedState>(options: {
  url?: string; getUrl?: () => Promise<string>; drillId: string; onState: (state: T) => void
  onStatus: (state: ConnectionState) => void; onError?: (message: string) => void
  onRecovered?: (count: number, complete: boolean) => void
  onAgentState?: (state:AgentLiveState) => void
  fetchState?: () => Promise<T>
}): () => void {
  let socket: WebSocket | null = null, stopped = false, attempt = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let stream: T | null = null, lastMessageAt = Date.now(), lastStateAt = Date.now(), lastSequence: number | null = null
  let agentStream:AgentLiveState|null=null, recovering=false
  async function open() {
    if (stopped) return
    options.onStatus(attempt ? 'stale' : 'connecting')
    stream = null
    agentStream = null
    const cursor = lastSequence === null ? '' : `&after_sequence=${lastSequence}`
    let url: string
    try {
      url = options.getUrl ? await options.getUrl() : options.url!
      if (stopped) return
      if (!url) throw new Error('实时连接地址缺失')
    } catch (error) {
      if (stopped) return
      options.onStatus('stale')
      const status = (error as { status?: number })?.status
      if ([401, 403, 404].includes(status ?? 0)) {
        options.onError?.('实时连接凭据已失效，请重新登录或获取新邀请。'); return
      }
      timer = setTimeout(open, Math.min(1000 * 2 ** attempt++, 10000))
      return
    }
    const current = new WebSocket(url + (url.includes('?') ? '&' : '?') + 'protocol=3' + cursor)
    socket = current; lastMessageAt = Date.now()
    current.onmessage = event => {
      if (stopped || socket !== current) return
      try {
        const message = JSON.parse(event.data) as LiveMessage<T>|AgentLiveMessage
        if ((message as {type:string}).type==='drill.transport_heartbeat') { lastMessageAt=Date.now(); return }
        if (message.type==='agent.snapshot' || message.type==='agent.delta') {
          agentStream=applyAgentMessage(agentStream,message)
          if(agentStream?.id!==options.drillId)throw new Error('计划场次不一致')
          lastMessageAt=Date.now()
          options.onAgentState?.(agentStream)
          return
        }
        if (!['drill.snapshot', 'drill.delta', 'drill.heartbeat', 'drill.catchup'].includes(message.type)) return
        if (message.type === 'drill.catchup') {
          lastMessageAt = Date.now()
          options.onRecovered?.(message.events.length, message.complete)
          return
        }
        stream = applyLiveMessage(stream, message)
        if (stream?.id !== options.drillId) throw new Error('场次不一致')
        if (typeof stream.latest_event_sequence === 'number') lastSequence = stream.latest_event_sequence
        lastMessageAt = Date.now(); lastStateAt=Date.now(); attempt = 0; options.onStatus('live')
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
    if(!stopped && options.fetchState && !recovering && (socket?.readyState!==WebSocket.OPEN || Date.now()-lastStateAt>15000)) {
      options.onStatus('stale')
      recovering=true
      options.fetchState().then(state=>{if(!stopped)options.onState(state)}).catch(()=>{}).finally(()=>{recovering=false})
    }
    if (!stopped && socket && socket.readyState < WebSocket.CLOSING && Date.now() - lastMessageAt > 45000) {
      options.onStatus('stale'); socket.close(4000, 'heartbeat timeout')
    }
  }, 4000)
  return () => { stopped = true; clearTimeout(timer); clearInterval(watchdog); socket?.close() }
}
