/** Same-origin HTTP client shared by page and feature modules. */
export function createApiClient({
  baseUrl = '/api',
  fetchImpl = (...args) => fetch(...args),
  onUnauthorized = () => {},
} = {}) {
  return async function request(path, options = {}, allowAnonymous = false) {
    const headers = new Headers(options.headers)
    headers.set('X-CityMate-Request', '1')
    if (options.body && !(options.body instanceof FormData)) {
      headers.set('Content-Type', 'application/json')
    }

    const response = await fetchImpl(baseUrl + path, {
      ...options,
      credentials: 'same-origin',
      headers,
    })
    const data = await response.json().catch(() => null)

    if (!response.ok) {
      if (response.status === 401) {
        onUnauthorized({ silent: allowAnonymous })
        if (allowAnonymous) return null
      }
      const message =
        typeof data?.detail === 'string'
          ? data.detail
          : `请求未完成（${response.status}），请检查输入后重试`
      throw new Error(message)
    }
    return data
  }
}
