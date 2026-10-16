import { useEffect, useState } from 'react'

export type MicPermission = 'unknown' | 'prompt' | 'granted' | 'denied'

/**
 * Microphone permission as reported by the Permissions API, so the UI can say
 * "your browser will ask" or "access is blocked" before the user taps the mic.
 * 'unknown' where the API or the 'microphone' query is unsupported (e.g. Firefox).
 */
export function useMicPermission(): MicPermission {
  const [permission, setPermission] = useState<MicPermission>('unknown')

  useEffect(() => {
    const permissions = (navigator as Navigator & { permissions?: Permissions }).permissions
    if (!permissions?.query) return
    let cancelled = false
    let status: PermissionStatus | null = null
    let query: Promise<PermissionStatus>
    try {
      query = permissions.query({ name: 'microphone' as PermissionName })
    } catch {
      return // some browsers throw synchronously for an unknown permission name
    }
    query
      .then((s) => {
        if (cancelled) return
        status = s
        setPermission(s.state as MicPermission)
        s.onchange = () => setPermission(s.state as MicPermission)
      })
      .catch(() => setPermission('unknown'))
    return () => {
      cancelled = true
      if (status) status.onchange = null
    }
  }, [])

  return permission
}
