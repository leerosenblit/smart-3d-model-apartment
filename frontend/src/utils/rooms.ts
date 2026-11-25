// Room detection: rooms are DERIVED from the walls (never stored), by rasterising the wall
// footprints, flood-filling the outside, and labelling what remains. Plan space, centimeters.
import type { Point, RoomStyle, Wall } from '../types'
import { pointInPolygon, rayPolygon, wallCorners, wallDir, wallLength } from './geometry'

export interface RoomInfo {
  id: number
  areaCm2: number
  /** centroid (may fall outside concave rooms) */
  cx: number
  cy: number
  /** a point guaranteed to be inside the room (cell closest to the centroid) */
  rep: Point
}

export interface RoomLayout {
  cell: number
  minX: number
  minY: number
  w: number
  h: number
  /** room id per cell, -1 = not a room (wall / outside / sliver) */
  labels: Int16Array
  rooms: RoomInfo[]
}

const MIN_ROOM_CM2 = 8000 // 0.8 m²: ignore slivers between walls
const MAX_CELLS = 1_200_000
const CLOSE_RADIUS_CM = 20 // closes wall gaps up to ~40 cm so slightly-open rooms still count as rooms
const ENVELOPE_RADIUS_CM = 100 // for deciding what is OUTSIDE the building: seals missed-wall gaps up to ~2 m
const DOOR_SEAL_CM = 130 // free wall ends facing another wall within this distance get a virtual closing segment

export function boxPass(src: Uint8Array, w: number, h: number, r: number, horizontal: boolean, dilate: boolean): Uint8Array {
  const out = new Uint8Array(src.length)
  if (horizontal) {
    for (let y = 0; y < h; y++) {
      const row = y * w
      for (let x = 0; x < w; x++) {
        const a = Math.max(0, x - r)
        const b = Math.min(w - 1, x + r)
        let v = dilate ? 0 : 1
        for (let i = a; i <= b; i++) {
          if (dilate ? src[row + i] : !src[row + i]) {
            v = dilate ? 1 : 0
            break
          }
        }
        out[row + x] = v
      }
    }
  } else {
    for (let y = 0; y < h; y++) {
      const a = Math.max(0, y - r)
      const b = Math.min(h - 1, y + r)
      for (let x = 0; x < w; x++) {
        let v = dilate ? 0 : 1
        for (let j = a; j <= b; j++) {
          if (dilate ? src[j * w + x] : !src[j * w + x]) {
            v = dilate ? 1 : 0
            break
          }
        }
        out[y * w + x] = v
      }
    }
  }
  return out
}

function fillPolygon(mask: Uint8Array, w: number, h: number, poly: Point[]): void {
  let minY = Infinity
  let maxY = -Infinity
  for (const p of poly) {
    minY = Math.min(minY, p.y)
    maxY = Math.max(maxY, p.y)
  }
  for (let y = Math.max(0, Math.ceil(minY - 0.5)); y <= Math.min(h - 1, Math.floor(maxY - 0.5)); y++) {
    const yc = y + 0.5
    const xs: number[] = []
    for (let i = 0; i < poly.length; i++) {
      const a = poly[i]
      const b = poly[(i + 1) % poly.length]
      if (a.y > yc !== b.y > yc) xs.push(a.x + ((yc - a.y) / (b.y - a.y)) * (b.x - a.x))
    }
    xs.sort((p, q) => p - q)
    for (let k = 0; k + 1 < xs.length; k += 2) {
      const x0 = Math.max(0, Math.ceil(xs[k] - 0.5))
      const x1 = Math.min(w - 1, Math.floor(xs[k + 1] - 0.5))
      for (let x = x0; x <= x1; x++) mask[y * w + x] = 1
    }
  }
}

export function detectRooms(walls: Wall[]): RoomLayout | null {
  if (walls.length < 3) return null
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  const polys = walls.map(wallCorners)
  // Doors and window gaps that were not bridged into a single wall: a free wall end that looks straight
  // at another wall within door distance is closed with a virtual segment, so doors separate rooms.
  walls.forEach((a, ai) => {
    const len = wallLength(a)
    if (len < 1) return
    const u = wallDir(a)
    for (const atEnd of [false, true]) {
      const e = atEnd ? { x: a.x2, y: a.y2 } : { x: a.x1, y: a.y1 }
      const dir = atEnd ? u : { x: -u.x, y: -u.y }
      if (polys.some((poly, bi) => bi !== ai && pointInPolygon(e, poly))) continue // joined to another wall
      let best: number | null = null
      polys.forEach((poly, bi) => {
        if (bi === ai) return
        const t = rayPolygon(e, dir, poly)
        if (t !== null && t > 1 && t <= DOOR_SEAL_CM && (best === null || t < best)) best = t
      })
      if (best !== null) {
        const f = { x: e.x + dir.x * (best + a.thicknessCm / 2), y: e.y + dir.y * (best + a.thicknessCm / 2) }
        polys.push(wallCorners({ ...a, x1: e.x, y1: e.y, x2: f.x, y2: f.y }))
      }
    }
  })
  for (const poly of polys)
    for (const p of poly) {
      minX = Math.min(minX, p.x)
      minY = Math.min(minY, p.y)
      maxX = Math.max(maxX, p.x)
      maxY = Math.max(maxY, p.y)
    }
  const spanX = maxX - minX
  const spanY = maxY - minY
  if (!(spanX > 50 && spanY > 50)) return null

  let cell = 4
  while (((spanX / cell) + 4) * ((spanY / cell) + 4) > MAX_CELLS) cell += 1
  const pad = Math.ceil(ENVELOPE_RADIUS_CM / cell) + 4 // keep a free outer ring so the exterior flood can wrap around
  const w = Math.ceil(spanX / cell) + pad * 2 + 1
  const h = Math.ceil(spanY / cell) + pad * 2 + 1
  const ox = minX - pad * cell
  const oy = minY - pad * cell

  // 1. rasterise wall footprints (door gaps are ignored on purpose: doors separate rooms)
  let solid = new Uint8Array(w * h)
  for (const poly of polys) {
    fillPolygon(
      solid,
      w,
      h,
      poly.map((p) => ({ x: (p.x - ox) / cell, y: (p.y - oy) / cell })),
    )
  }
  // 2. morphological closing: seal tiny gaps left by imperfect corners / detection
  const close = (src: Uint8Array, radius: number): Uint8Array => {
    let c = boxPass(boxPass(src, w, h, radius, true, true), w, h, radius, false, true)
    c = boxPass(boxPass(c, w, h, radius, true, false), w, h, radius, false, false)
    const out = new Uint8Array(src.length)
    for (let i = 0; i < out.length; i++) out[i] = src[i] | c[i]
    return out
  }
  // envelope: heavily closed, used ONLY to decide which cells are outside the building, so a few
  // undetected wall segments can't make whole rooms "leak" to the outside and lose their floor
  const envelope = close(solid, Math.max(2, Math.round(ENVELOPE_RADIUS_CM / cell)))
  // light closing: seals small corner gaps; rooms still split at doors / interior walls
  solid = close(solid, Math.max(1, Math.round(CLOSE_RADIUS_CM / cell)))

  // 3. flood-fill the exterior from the padded border
  const outside = new Uint8Array(w * h)
  const stack: number[] = [0]
  outside[0] = 1
  while (stack.length) {
    const i = stack.pop()!
    const x = i % w
    const y = (i / w) | 0
    const nb = [x > 0 ? i - 1 : -1, x < w - 1 ? i + 1 : -1, y > 0 ? i - w : -1, y < h - 1 ? i + w : -1]
    for (const j of nb) {
      if (j >= 0 && !envelope[j] && !outside[j]) {
        outside[j] = 1
        stack.push(j)
      }
    }
  }

  // 3b. rescue: a free cell with a wall somewhere to its left, right, above AND below is indoors, even if
  // the flood leaked through an undetected wall segment (typical for big open rooms next to terraces)
  const bits = new Uint8Array(w * h)
  for (let y = 0; y < h; y++) {
    let seen = false
    for (let x = 0; x < w; x++) {
      if (solid[y * w + x]) seen = true
      if (seen) bits[y * w + x] |= 1
    }
    seen = false
    for (let x = w - 1; x >= 0; x--) {
      if (solid[y * w + x]) seen = true
      if (seen) bits[y * w + x] |= 2
    }
  }
  for (let x = 0; x < w; x++) {
    let seen = false
    for (let y = 0; y < h; y++) {
      if (solid[y * w + x]) seen = true
      if (seen) bits[y * w + x] |= 4
    }
    seen = false
    for (let y = h - 1; y >= 0; y--) {
      if (solid[y * w + x]) seen = true
      if (seen) bits[y * w + x] |= 8
    }
  }
  for (let i = 0; i < outside.length; i++) if (outside[i] && bits[i] === 15) outside[i] = 0

  // 4. label the enclosed interior regions
  const raw = new Int32Array(w * h).fill(-1)
  const found: { count: number; sx: number; sy: number; cells: number[] }[] = []
  for (let start = 0; start < solid.length; start++) {
    if (solid[start] || outside[start] || raw[start] !== -1) continue
    const id = found.length
    const rec = { count: 0, sx: 0, sy: 0, cells: [] as number[] }
    raw[start] = id
    stack.push(start)
    while (stack.length) {
      const i = stack.pop()!
      const x = i % w
      const y = (i / w) | 0
      rec.count++
      rec.sx += x
      rec.sy += y
      rec.cells.push(i)
      const nb = [x > 0 ? i - 1 : -1, x < w - 1 ? i + 1 : -1, y > 0 ? i - w : -1, y < h - 1 ? i + w : -1]
      for (const j of nb) {
        if (j >= 0 && !solid[j] && !outside[j] && raw[j] === -1) {
          raw[j] = id
          stack.push(j)
        }
      }
    }
    found.push(rec)
  }

  const labels = new Int16Array(w * h).fill(-1)
  const rooms: RoomInfo[] = []
  for (const rec of found) {
    const area = rec.count * cell * cell
    if (area < MIN_ROOM_CM2) continue
    const mx = rec.sx / rec.count
    const my = rec.sy / rec.count
    let best = rec.cells[0]
    let bestD = Infinity
    for (const i of rec.cells) {
      const d = ((i % w) - mx) ** 2 + (((i / w) | 0) - my) ** 2
      if (d < bestD) {
        bestD = d
        best = i
      }
    }
    const id = rooms.length
    for (const i of rec.cells) labels[i] = id
    rooms.push({
      id,
      areaCm2: area,
      cx: ox + (mx + 0.5) * cell,
      cy: oy + (my + 0.5) * cell,
      rep: { x: Math.round(ox + ((best % w) + 0.5) * cell), y: Math.round(oy + (((best / w) | 0) + 0.5) * cell) },
    })
  }
  return rooms.length ? { cell, minX: ox, minY: oy, w, h, labels, rooms } : null
}

/** Room id at a plan point, or -1. */
export function roomAt(layout: RoomLayout, x: number, y: number): number {
  const gx = Math.floor((x - layout.minX) / layout.cell)
  const gy = Math.floor((y - layout.minY) / layout.cell)
  if (gx < 0 || gy < 0 || gx >= layout.w || gy >= layout.h) return -1
  return layout.labels[gy * layout.w + gx]
}

/** The stored style (last one wins) whose anchor point lies inside the given room. */
export function styleIndexForRoom(layout: RoomLayout, styles: RoomStyle[], roomId: number): number {
  for (let i = styles.length - 1; i >= 0; i--) if (roomAt(layout, styles[i].x, styles[i].y) === roomId) return i
  return -1
}

export const roomKey = (room: RoomInfo): string => `${room.rep.x}:${room.rep.y}`
export const parseRoomKey = (id: string): Point => {
  const [x, y] = id.split(':').map(Number)
  return { x, y }
}
