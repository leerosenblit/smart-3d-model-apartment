import type { FloorMaterialId, RoomKind } from '../types'

export interface RoomKindInfo {
  label: string
  material: FloorMaterialId
}

export const ROOM_KINDS: Record<RoomKind, RoomKindInfo> = {
  bedroom: { label: 'חדר שינה', material: 'oak' },
  master: { label: 'חדר שינה הורים', material: 'oak' },
  kids: { label: 'חדר ילדים', material: 'oak' },
  office: { label: 'חדר עבודה', material: 'oak' },
  living: { label: 'סלון', material: 'oak' },
  dining: { label: 'פינת אוכל', material: 'oak' },
  kitchen: { label: 'מטבח', material: 'tile_beige' },
  bathroom: { label: 'חדר רחצה', material: 'tile_white' },
  toilet: { label: 'שירותים', material: 'tile_white' },
  laundry: { label: 'חדר כביסה', material: 'tile_white' },
  hallway: { label: 'מסדרון', material: 'walnut' },
  balcony: { label: 'מרפסת', material: 'tile_beige' },
  closet: { label: 'מלתחה', material: 'oak' },
  storage: { label: 'מחסן', material: 'concrete' },
  room: { label: 'חדר', material: 'oak' },
}

export const ROOM_KIND_ORDER = Object.keys(ROOM_KINDS) as RoomKind[]
export const isBedroomKind = (k?: RoomKind | null): boolean => k === 'bedroom' || k === 'master' || k === 'kids'
