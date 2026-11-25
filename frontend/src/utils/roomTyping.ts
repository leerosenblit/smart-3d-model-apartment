// Decides what each detected room IS (bedroom, living room, bathroom, ...) from OCR name hints first and
// size / shape / door heuristics otherwise, then gives it a Hebrew name and a sensible default floor.
import type { Opening, RoomHint, RoomKind, RoomStyle, Wall } from '../types'
import { wallDir } from './geometry'
import { ROOM_KINDS, isBedroomKind } from './roomKinds'
import { roomAt } from './rooms'
import type { RoomLayout } from './rooms'

export interface RoomStats {
  id: number
  areaM2: number
  minX: number
  minY: number
  maxX: number
  maxY: number
  w: number
  h: number
  aspect: number
  doors: number
  windows: number
}

export function roomStats(layout: RoomLayout, walls: Wall[], openings: Opening[]): RoomStats[] {
  const { w, h, cell, labels } = layout
  const b = layout.rooms.map(() => ({ x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity }))
  for (let gy = 0; gy < h; gy++)
    for (let gx = 0; gx < w; gx++) {
      const id = labels[gy * w + gx]
      if (id < 0) continue
      const r = b[id]
      if (gx < r.x0) r.x0 = gx
      if (gx > r.x1) r.x1 = gx
      if (gy < r.y0) r.y0 = gy
      if (gy > r.y1) r.y1 = gy
    }
  const stats: RoomStats[] = layout.rooms.map((room) => {
    const r = b[room.id]
    const minX = layout.minX + r.x0 * cell
    const minY = layout.minY + r.y0 * cell
    const maxX = layout.minX + (r.x1 + 1) * cell
    const maxY = layout.minY + (r.y1 + 1) * cell
    const bw = maxX - minX
    const bh = maxY - minY
    return {
      id: room.id,
      areaM2: room.areaCm2 / 10000,
      minX,
      minY,
      maxX,
      maxY,
      w: bw,
      h: bh,
      aspect: Math.max(bw, bh) / Math.max(1, Math.min(bw, bh)),
      doors: 0,
      windows: 0,
    }
  })
  // which rooms does each opening touch? probe both sides of the wall at the opening's centre
  for (const o of openings) {
    const wall = walls.find((x) => x.id === o.wallId)
    if (!wall) continue
    const d = wallDir(wall)
    const c = { x: wall.x1 + d.x * o.offsetCm, y: wall.y1 + d.y * o.offsetCm }
    const reach = wall.thicknessCm / 2 + 25
    const seen = new Set<number>()
    for (const side of [1, -1]) {
      const id = roomAt(layout, c.x - d.y * reach * side, c.y + d.x * reach * side)
      if (id >= 0 && !seen.has(id)) {
        seen.add(id)
        if (o.kind === 'door') stats[id].doors++
        else stats[id].windows++
      }
    }
  }
  return stats
}

const HINT_PRIORITY: RoomKind[] = [
  'toilet', 'bathroom', 'laundry', 'kitchen', 'balcony', 'closet', 'storage', 'hallway', 'office', 'kids', 'master', 'bedroom', 'living', 'dining',
]

function hintRoom(layout: RoomLayout, h: RoomHint): number {
  const direct = roomAt(layout, h.x_cm, h.y_cm)
  if (direct >= 0) return direct
  for (let r = 20; r <= 120; r += 20)
    for (let a = 0; a < 8; a++) {
      const id = roomAt(layout, h.x_cm + Math.cos((a * Math.PI) / 4) * r, h.y_cm + Math.sin((a * Math.PI) / 4) * r)
      if (id >= 0) return id
    }
  return -1
}

export interface TypedRoom {
  id: number
  kind: RoomKind
  name: string
}

export function classifyRooms(layout: RoomLayout, hints: RoomHint[], walls: Wall[], openings: Opening[]): TypedRoom[] {
  const stats = roomStats(layout, walls, openings)
  const kinds: (RoomKind | null)[] = stats.map(() => null)
  const hinted: Set<string>[] = stats.map(() => new Set<string>())

  // 1. OCR hints
  for (const h of hints) {
    const id = hintRoom(layout, h)
    if (id >= 0) h.kinds.forEach((k) => hinted[id].add(k))
  }
  stats.forEach((s, i) => {
    const hs = hinted[i]
    if (!hs.size) return
    if (hs.has('master') && hs.has('bathroom')) kinds[i] = 'bathroom'
    else kinds[i] = HINT_PRIORITY.find((k) => hs.has(k)) ?? null
    if (kinds[i] === 'dining' && s.areaM2 < 8) kinds[i] = null
  })

  // 2. heuristics for the rest
  const largest = stats.reduce<RoomStats | null>((m, s) => (s.areaM2 > (m?.areaM2 ?? 0) ? s : m), null)
  stats.forEach((s, i) => {
    if (kinds[i]) return
    if (s.areaM2 < 2.6) kinds[i] = s.doors > 0 ? 'toilet' : 'closet'
    else if (s.areaM2 < 6.5) kinds[i] = 'bathroom'
    else if (s.aspect >= 3.2 && Math.min(s.w, s.h) <= 170) kinds[i] = 'hallway'
    else if (s.areaM2 >= 18 && s === largest) kinds[i] = 'living'
    else if (s.areaM2 >= 7) kinds[i] = 'bedroom'
    else kinds[i] = 'room'
  })

  // 3. consistency: an apartment has a living room; the biggest bedroom becomes the master when none is labelled
  if (!kinds.includes('living')) {
    const pick = stats
      .filter((s) => (kinds[s.id] === 'room' || kinds[s.id] === 'dining') && s.areaM2 >= 12)
      .sort((a, b) => b.areaM2 - a.areaM2)[0]
    if (pick) kinds[pick.id] = 'living'
  }
  const bedrooms = stats.filter((s) => kinds[s.id] === 'bedroom')
  if (!kinds.includes('master') && bedrooms.length >= 2) {
    const biggest = [...bedrooms].sort((a, b) => b.areaM2 - a.areaM2)[0]
    if (biggest.areaM2 >= 12) kinds[biggest.id] = 'master'
  }

  // 4. names (numbered when a kind repeats), ordered top-to-bottom then left-to-right
  const order = [...stats].sort((a, b) => Math.round(a.minY / 150) - Math.round(b.minY / 150) || a.minX - b.minX)
  const total = new Map<RoomKind, number>()
  kinds.forEach((k) => k && total.set(k, (total.get(k) ?? 0) + 1))
  const seen = new Map<RoomKind, number>()
  const out: TypedRoom[] = []
  for (const s of order) {
    const kind = kinds[s.id] as RoomKind
    const n = (seen.get(kind) ?? 0) + 1
    seen.set(kind, n)
    let name = ROOM_KINDS[kind].label
    if (kind === 'living' && hinted[s.id].has('dining')) name = 'סלון ופינת אוכל'
    if ((total.get(kind) ?? 0) > 1) name += ` ${n}`
    out.push({ id: s.id, kind, name })
  }
  return out.sort((a, b) => a.id - b.id)
}

/** RoomStyle entries (anchor = a point inside each room) ready to store. */
export function stylesFromTyping(layout: RoomLayout, typed: TypedRoom[]): RoomStyle[] {
  return typed.map((t) => ({
    x: layout.rooms[t.id].rep.x,
    y: layout.rooms[t.id].rep.y,
    material: ROOM_KINDS[t.kind].material,
    name: t.name,
    kind: t.kind,
  }))
}

export { isBedroomKind }
