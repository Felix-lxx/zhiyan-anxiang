import { ApiError, type ApiClient } from './client'

export function commandForPath(path: string, arguments_: unknown) {
  const exact: Record<string, string> = { '/state': 'state', '/inject': 'event.inject', '/residents': 'residents.assign', '/robot': 'robot.command', '/searches': 'search.assign', '/participant-actions': 'participant.feedback', '/director/config': 'director.configure' }
  const road = path.match(/^\/roads\/([^/]+)\/reopen$/), task = path.match(/^\/tasks\/([^/]+)\/actions$/)
  const kind = exact[path] ?? (road ? 'road.reopen' : task ? 'task.action' : undefined)
  return kind ? { kind, arguments: arguments_ ?? {}, target_id: road?.[1] ?? task?.[1] ?? null } : null
}

/** Retry uncertain transport results with the same ID; the server executes only once. */
export async function sendCommand<T>(api: ApiClient, drillId: string, path: string, body?: unknown, method: 'POST' | 'PATCH' = 'POST', expectedSequence?: number): Promise<T> {
  const operation = commandForPath(path, body)
  if (!operation) return api.request<T>(`/drills/${drillId}${path}`, { method, body })
  const id = globalThis.crypto?.randomUUID?.() ?? `cmd-${Date.now()}-${Math.random().toString(36).slice(2)}`
  const payload = { ...operation, command_id: id, ...(expectedSequence === undefined ? {} : { expected_sequence: expectedSequence }) }
  const execute = () => api.post<T>(`/drills/${drillId}/commands`, payload, { signal: AbortSignal.timeout(20000) })
  try { return await execute() }
  catch (error) {
    if (error instanceof ApiError && error.status < 500) throw error
    try { return await execute() }
    catch (retryError) {
      if (retryError instanceof ApiError && retryError.status < 500) throw retryError
      throw new Error('连接中断，指令结果暂未确认。恢复连接后请在执行进度核对结果，再决定是否重新下令。')
    }
  }
}
