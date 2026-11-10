const TOKEN_KEY = 'ups-controller-token'

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

export function setToken(token) {
  try {
    localStorage.setItem(TOKEN_KEY, token)
  } catch {
    /* 無法儲存時只在本次頁面有效 */
  }
}

export class ApiError extends Error {
  constructor(status, message) {
    super(message)
    this.status = status
  }
}

export async function api(path, { method = 'GET', body } = {}) {
  const headers = { Accept: 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const response = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  let data = null
  try {
    data = await response.json()
  } catch {
    /* 非 JSON 回應 */
  }
  if (!response.ok) {
    throw new ApiError(response.status, data?.detail || `HTTP ${response.status}`)
  }
  return data
}

export const post = (path, body) => api(path, { method: 'POST', body })

export function streamUrl() {
  const token = getToken()
  return token ? `/api/stream?token=${encodeURIComponent(token)}` : '/api/stream'
}
