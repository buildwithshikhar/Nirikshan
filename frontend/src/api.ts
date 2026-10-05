export const API_URL = import.meta.env.VITE_API_URL ?? ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!res.ok) {
    let detail = await res.text()
    try {
      detail = JSON.parse(detail).detail ?? detail
    } catch {
      // keep raw text
    }
    throw new Error(String(detail))
  }
  return res.status === 204 ? (undefined as T) : res.json()
}

export const api = {
  health: () => request<{ status: string }>('/health'),
}
