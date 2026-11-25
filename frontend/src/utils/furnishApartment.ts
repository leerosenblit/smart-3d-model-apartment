import { api } from '../api/client'
import { ensureModel } from '../hooks/useModelGeneration'
import { useAppStore } from '../store/useAppStore'
import type { Category, Product } from '../types'
import { planFurniture, placementsToItems } from './autoFurnish'
import type { FurnishRoom } from './autoFurnish'
import { computeFloor } from './floorTexture'
import { classifyRooms } from './roomTyping'
import { roomStats } from './roomTyping'

const NEEDED: Category[] = ['bed', 'wardrobe', 'storage', 'desk', 'sofa', 'tv_unit', 'coffee_table', 'dining_table', 'chair']

/**
 * Furnish the detected rooms (bedrooms, living room) from the real catalog and add the items to the scene
 * as ONE undo step. `replace` swaps out any existing furniture first. Returns the number of items placed.
 */
export async function furnishApartment(opts: { replace?: boolean; quiet?: boolean } = {}): Promise<number> {
  const st = useAppStore.getState()
  const floor = computeFloor(st.walls, st.roomStyles, st.openings)
  if (!floor) {
    if (!opts.quiet) st.toast('לא זוהו חדרים לריהוט — ודאו שהקירות סגורים', 'info')
    return 0
  }

  const stats = roomStats(floor.layout, st.walls, st.openings)
  // rooms without a stored kind (hand-drawn walls) get the heuristic classification
  const typed = classifyRooms(floor.layout, [], st.walls, st.openings)
  const rooms: FurnishRoom[] = floor.rooms.map((r) => {
    const s = stats[r.room.id]
    return {
      id: r.room.id,
      kind: r.kind ?? typed[r.room.id].kind,
      areaM2: r.areaM2,
      minX: s.minX,
      minY: s.minY,
      maxX: s.maxX,
      maxY: s.maxY,
    }
  })

  const lists = await Promise.all(
    NEEDED.map((category) => api.listProducts({ category, sort_by: 'featured', limit: 400 }).catch(() => [] as Product[])),
  )
  const catalog: Partial<Record<Category, Product[]>> = {}
  NEEDED.forEach((c, i) => (catalog[c] = lists[i]))

  const placements = planFurniture(floor.layout, rooms, st.walls, st.openings, catalog)
  if (!placements.length) {
    if (!opts.quiet) st.toast('לא נמצא ריהוט מתאים לחדרים בקטלוג', 'info')
    return 0
  }
  const items = placementsToItems(placements)
  useAppStore.getState().addPlacedItems(items, !!opts.replace)
  // lazy 3D: each distinct product is generated once (cached afterwards)
  new Set(items.filter((i) => !i.fixture).map((i) => i.productId)).forEach((id) => void ensureModel(id))
  return items.length
}
