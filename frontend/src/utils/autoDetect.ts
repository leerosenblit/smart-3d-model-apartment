import { api } from '../api/client'
import { useAppStore } from '../store/useAppStore'

/**
 * Detect walls/doors/windows on the current floorplan and apply them (one undo step).
 * With `ppc = null` the backend estimates the scale from the typical wall thickness; the scale is
 * then flagged as "estimated" so the UI can invite a precise calibration (which re-runs detection).
 */
export async function autoDetectWalls(ppc: number | null): Promise<boolean> {
  const st = useAppStore.getState()
  if (!st.floorplanUrl) return false
  try {
    const res = await api.detectWalls(st.floorplanUrl, ppc)
    if (res.walls.length === 0) {
      st.toast('לא זוהו קירות אוטומטית. הקירות צריכים להיות עבים וצבועים/כהים — אפשר לצייר ידנית', 'error')
      if (ppc === null) st.setTool('calibrate')
      return false
    }
    if (res.scale_estimated && res.pixels_per_cm) st.setEstimatedScale(res.pixels_per_cm)
    st.applyDetectedWalls(res.walls, true)
    const doors = res.walls.reduce((n, w) => n + w.openings.filter((o) => o.kind === 'door').length, 0)
    const windows = res.walls.reduce((n, w) => n + w.openings.filter((o) => o.kind === 'window').length, 0)
    st.toast(
      `זוהו אוטומטית ${res.walls.length} קירות, ${doors} דלתות, ${windows} חלונות` +
        (res.scale_estimated ? ' · קנה המידה הוערך — לכיול מדויק השתמשו בכיול' : '') +
        ' · ניתן לתקן ב-2D או לבטל',
      'success',
    )
    return true
  } catch (e) {
    st.toast(e instanceof Error ? e.message : 'שגיאה בזיהוי הקירות', 'error')
    return false
  }
}
