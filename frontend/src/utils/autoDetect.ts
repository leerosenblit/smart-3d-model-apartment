import { api } from '../api/client'
import { useAppStore } from '../store/useAppStore'
import { computeFloor } from './floorTexture'
import { classifyRooms, stylesFromTyping } from './roomTyping'
import { furnishApartment } from './furnishApartment'

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
    // name + type every room (OCR labels from the plan first, size/shape heuristics otherwise)
    const now = useAppStore.getState()
    const floor = computeFloor(now.walls, [], now.openings)
    if (floor) {
      const typed = classifyRooms(floor.layout, res.room_hints ?? [], now.walls, now.openings)
      now.setRoomStyles(stylesFromTyping(floor.layout, typed))
    }
    // furnish bedrooms + living room from the catalog (only into an empty apartment, never over the user's items)
    let furnished = 0
    if (useAppStore.getState().autoFurnish && useAppStore.getState().placedItems.length === 0) {
      furnished = await furnishApartment({ quiet: true })
    }
    const doors = res.walls.reduce((n, w) => n + w.openings.filter((o) => o.kind === 'door').length, 0)
    const windows = res.walls.reduce((n, w) => n + w.openings.filter((o) => o.kind === 'window').length, 0)
    st.toast(
      `זוהו אוטומטית ${res.walls.length} קירות, ${doors} דלתות, ${windows} חלונות` +
        (furnished ? ` · רוהטו ${furnished} פריטים אוטומטית` : '') +
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
