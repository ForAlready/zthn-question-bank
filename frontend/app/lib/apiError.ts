/** Normalize FastAPI / ofetch error payloads into a readable toast message. */
export function apiErrorMessage(error: unknown, fallback = '操作失败'): string {
  const data = (error as { data?: { detail?: unknown }; message?: string })?.data
  const detail = data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (detail && typeof detail === 'object') {
    const obj = detail as { message?: string; errors?: string[] }
    if (obj.message) {
      if (Array.isArray(obj.errors) && obj.errors.length) {
        return `${obj.message}：${obj.errors.slice(0, 3).join('；')}`
      }
      return obj.message
    }
  }
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0] as { msg?: string }
    if (first?.msg) return first.msg
  }
  const msg = (error as { message?: string })?.message
  if (msg && msg !== 'FetchError') return msg
  return fallback
}
