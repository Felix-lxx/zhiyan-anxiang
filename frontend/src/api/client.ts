export interface ApiRequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown
  auth?: boolean
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly payload: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

type TokenSource = () => string | null | undefined
let unauthorizedHandler: (() => void) | undefined
let tokenRefreshHandler: (() => Promise<string | null>) | undefined
let refreshInFlight: Promise<string | null> | null = null
export function setUnauthorizedHandler(handler: () => void) { unauthorizedHandler = handler }
export function setTokenRefreshHandler(handler: () => Promise<string | null>) { tokenRefreshHandler = handler }

async function refreshAccessToken(): Promise<string | null> {
  if (!tokenRefreshHandler) return null
  if (!refreshInFlight) refreshInFlight = tokenRefreshHandler().catch(() => null).finally(() => { refreshInFlight = null })
  return refreshInFlight
}

function messageFrom(payload: unknown, fallback: string): string {
  if (typeof payload === 'object' && payload !== null && 'detail' in payload) {
    const detail = (payload as { detail?: unknown }).detail
    if (typeof detail === 'string' && detail.trim()) return detail
    if (Array.isArray(detail)) return detail.map(item => typeof item?.msg === 'string' ? item.msg : '').filter(Boolean).join('；') || fallback
  }
  return fallback
}

function parsePayload(text: string): unknown {
  if (!text) return null
  try { return JSON.parse(text) } catch { return text }
}

export class ApiClient {
  constructor(
    readonly baseUrl: string,
    private readonly tokenSource: TokenSource = () => null,
    private readonly onUnauthorized?: () => void,
  ) {}

  /** The sole HTTP transport; public participant requests never carry operator credentials. */
  private async response(path: string, options: RequestInit = {}, auth = true): Promise<Response> {
    const url = path.startsWith(this.baseUrl + '/') ? path : `${this.baseUrl}${path}`
    const publicRequest = !auth || /\/participant\//.test(url) || /\/auth\/(login|refresh)$|\/health$/.test(url)
    const headers = new Headers(options.headers)
    const token = this.tokenSource()
    if (publicRequest) headers.delete('Authorization')
    else if (token) headers.set('Authorization', `Bearer ${token}`)
    const request = { ...options, headers, credentials: options.credentials ?? 'include' as RequestCredentials, signal: options.signal ?? AbortSignal.timeout(120_000) }
    let response = await fetch(url, request)
    if (response.status === 401 && !publicRequest && headers.has('Authorization')) {
      const refreshed = await refreshAccessToken()
      if (refreshed) {
        headers.set('Authorization', `Bearer ${refreshed}`)
        response = await fetch(url, request)
      }
    }
    if (!response.ok) {
      const payload = parsePayload(await response.text())
      if (response.status === 401 && !publicRequest && headers.has('Authorization')) (this.onUnauthorized ?? unauthorizedHandler)?.()
      throw new ApiError(messageFrom(payload, `请求失败（${response.status}）`), response.status, payload)
    }
    return response
  }

  async request<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
    const { body, auth = true, headers: suppliedHeaders, ...requestOptions } = options
    const headers = new Headers(suppliedHeaders)
    const token = this.tokenSource()
    if (auth && token) headers.set('Authorization', `Bearer ${token}`)

    let requestBody: BodyInit | undefined
    if (body !== undefined) {
      if (body instanceof FormData || body instanceof Blob || body instanceof URLSearchParams || typeof body === 'string') requestBody = body
      else {
        headers.set('Content-Type', 'application/json')
        requestBody = JSON.stringify(body)
      }
    }

    const response = await this.response(path, { ...requestOptions, headers, body: requestBody }, auth)
    const payload = parsePayload(await response.text())
    return payload as T
  }

  get<T>(path: string, options: ApiRequestOptions = {}) { return this.request<T>(path, { ...options, method: 'GET' }) }
  post<T>(path: string, body?: unknown, options: ApiRequestOptions = {}) { return this.request<T>(path, { ...options, method: 'POST', body }) }
  patch<T>(path: string, body?: unknown, options: ApiRequestOptions = {}) { return this.request<T>(path, { ...options, method: 'PATCH', body }) }
  delete<T>(path: string, options: ApiRequestOptions = {}) { return this.request<T>(path, { ...options, method: 'DELETE' }) }

  websocketUrl(path: string): string {
    const base = new URL(this.baseUrl, location.origin)
    base.protocol = base.protocol === 'https:' ? 'wss:' : 'ws:'
    base.pathname = path.split('?')[0]!
    base.search = path.includes('?') ? path.slice(path.indexOf('?')) : ''
    return base.toString()
  }
}

export function createApiClient(baseUrl: string, tokenSource?: TokenSource, onUnauthorized?: () => void) {
  return new ApiClient(baseUrl.replace(/\/$/, ''), tokenSource, onUnauthorized)
}
