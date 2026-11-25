// Pure 2D plan geometry. Plan space: x → right, y → down, all in centimeters.
import type { Opening, PlacedItem, Point, SceneState, Wall } from '../types'

const EPS = 1e-9

export const dist = (a: Point, b: Point): number => Math.hypot(b.x - a.x, b.y - a.y)
export const wallLength = (w: Wall): number => Math.hypot(w.x2 - w.x1, w.y2 - w.y1)
/** Wall direction angle in radians (plan space, clockwise-on-screen positive). */
export const wallAngle = (w: Wall): number => Math.atan2(w.y2 - w.y1, w.x2 - w.x1)
export const wallDir = (w: Wall): Point => {
  const l = wallLength(w) || 1
  return { x: (w.x2 - w.x1) / l, y: (w.y2 - w.y1) / l }
}
export const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v))
export const roundTo = (v: number, step: number): number => Math.round(v / step) * step

// ---------------------------------------------------------------- projection / snapping

export function projectOnSegment(p: Point, a: Point, b: Point): { t: number; point: Point; distance: number } {
  const dx = b.x - a.x
  const dy = b.y - a.y
  const len2 = dx * dx + dy * dy
  const t = len2 < EPS ? 0 : clamp(((p.x - a.x) * dx + (p.y - a.y) * dy) / len2, 0, 1)
  const point = { x: a.x + dx * t, y: a.y + dy * t }
  return { t, point, distance: dist(p, point) }
}

export function nearestWall(
  p: Point,
  walls: Wall[],
  maxDist: number,
): { wall: Wall; offsetCm: number; point: Point; distance: number } | null {
  let best: { wall: Wall; offsetCm: number; point: Point; distance: number } | null = null
  for (const w of walls) {
    const pr = projectOnSegment(p, { x: w.x1, y: w.y1 }, { x: w.x2, y: w.y2 })
    const d = Math.max(0, pr.distance - w.thicknessCm / 2)
    if (d <= maxDist && (!best || d < best.distance)) {
      best = { wall: w, offsetCm: pr.t * wallLength(w), point: pr.point, distance: d }
    }
  }
  return best
}

/** Snap p to the nearest wall endpoint within `threshold` cm. */
export function snapToEndpoints(p: Point, walls: Wall[], threshold: number): Point | null {
  let best: Point | null = null
  let bestD = threshold
  for (const w of walls) {
    for (const e of [{ x: w.x1, y: w.y1 }, { x: w.x2, y: w.y2 }]) {
      const d = dist(p, e)
      if (d <= bestD) {
        best = e
        bestD = d
      }
    }
  }
  return best
}

/** 90° orthogonal snap relative to `from`: keep the dominant axis, zero the other. */
export function orthoSnap(from: Point, p: Point): Point {
  const dx = p.x - from.x
  const dy = p.y - from.y
  return Math.abs(dx) >= Math.abs(dy) ? { x: p.x, y: from.y } : { x: from.x, y: p.y }
}

// ---------------------------------------------------------------- polygons

export const wallCorners = (w: Wall): Point[] => {
  const d = wallDir(w)
  const nx = -d.y * (w.thicknessCm / 2)
  const ny = d.x * (w.thicknessCm / 2)
  return [
    { x: w.x1 + nx, y: w.y1 + ny },
    { x: w.x2 + nx, y: w.y2 + ny },
    { x: w.x2 - nx, y: w.y2 - ny },
    { x: w.x1 - nx, y: w.y1 - ny },
  ]
}

export const degToRad = (d: number): number => (d * Math.PI) / 180

export function itemCorners(
  it: Pick<PlacedItem, 'xCm' | 'zCm' | 'rotationDeg' | 'widthCm' | 'depthCm'>,
): Point[] {
  const a = degToRad(it.rotationDeg)
  const c = Math.cos(a)
  const s = Math.sin(a)
  const hw = it.widthCm / 2
  const hd = it.depthCm / 2
  return [
    [-hw, -hd],
    [hw, -hd],
    [hw, hd],
    [-hw, hd],
  ].map(([x, y]) => ({ x: it.xCm + x * c - y * s, y: it.zCm + x * s + y * c }))
}

export function pointInPolygon(p: Point, poly: Point[]): boolean {
  let inside = false
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const a = poly[i]
    const b = poly[j]
    if (a.y > p.y !== b.y > p.y && p.x < ((b.x - a.x) * (p.y - a.y)) / (b.y - a.y) + a.x) inside = !inside
  }
  return inside
}

/** Ray (origin + t·dir, t ≥ 0) vs segment ab. Returns t or null. */
export function raySegment(origin: Point, dir: Point, a: Point, b: Point): number | null {
  const ex = b.x - a.x
  const ey = b.y - a.y
  const denom = dir.x * ey - dir.y * ex
  if (Math.abs(denom) < EPS) return null
  const ox = a.x - origin.x
  const oy = a.y - origin.y
  const t = (ox * ey - oy * ex) / denom
  const u = (ox * dir.y - oy * dir.x) / denom
  if (t >= 0 && u >= 0 && u <= 1) return t
  return null
}

export function rayPolygon(origin: Point, dir: Point, poly: Point[]): number | null {
  let best: number | null = null
  for (let i = 0; i < poly.length; i++) {
    const t = raySegment(origin, dir, poly[i], poly[(i + 1) % poly.length])
    if (t !== null && (best === null || t < best)) best = t
  }
  return best
}

// ---------------------------------------------------------------- clearance

export interface Clearance {
  /** side name in the item's local frame */
  side: 'front' | 'back' | 'left' | 'right'
  from: Point
  to: Point
  cm: number
  /** what was hit */
  target: 'wall' | 'item'
}

const MAX_CLEARANCE = 600

/**
 * Distance from each side of the selected item to the nearest wall/other item,
 * cast outward from the midpoint of each edge. Shared by 2D and 3D overlays.
 */
export function computeClearances(item: PlacedItem, scene: Pick<SceneState, 'walls' | 'placedItems'>): Clearance[] {
  const a = degToRad(item.rotationDeg)
  const ux = { x: Math.cos(a), y: Math.sin(a) } // local +x (width axis)
  const uz = { x: -Math.sin(a), y: Math.cos(a) } // local +z (depth axis)
  const c = { x: item.xCm, y: item.zCm }
  const sides: { side: Clearance['side']; dir: Point; half: number }[] = [
    { side: 'right', dir: ux, half: item.widthCm / 2 },
    { side: 'left', dir: { x: -ux.x, y: -ux.y }, half: item.widthCm / 2 },
    { side: 'back', dir: { x: -uz.x, y: -uz.y }, half: item.depthCm / 2 },
    { side: 'front', dir: uz, half: item.depthCm / 2 },
  ]
  const obstacles: { poly: Point[]; target: 'wall' | 'item' }[] = [
    ...scene.walls.map((w) => ({ poly: wallCorners(w), target: 'wall' as const })),
    ...scene.placedItems.filter((o) => o.id !== item.id).map((o) => ({ poly: itemCorners(o), target: 'item' as const })),
  ]
  const out: Clearance[] = []
  for (const s of sides) {
    const from = { x: c.x + s.dir.x * s.half, y: c.y + s.dir.y * s.half }
    let best: { t: number; target: 'wall' | 'item' } | null = null
    for (const ob of obstacles) {
      if (pointInPolygon(from, ob.poly)) {
        best = { t: 0, target: ob.target }
        break
      }
      const t = rayPolygon(from, s.dir, ob.poly)
      if (t !== null && t <= MAX_CLEARANCE && (!best || t < best.t)) best = { t, target: ob.target }
    }
    if (best) {
      out.push({
        side: s.side,
        from,
        to: { x: from.x + s.dir.x * best.t, y: from.y + s.dir.y * best.t },
        cm: best.t,
        target: best.target,
      })
    }
  }
  return out
}

// ---------------------------------------------------------------- item snapping

/** Snap an item's center so its edge sits flush against a nearby wall face. */
export function snapItemToWalls(
  item: Pick<PlacedItem, 'xCm' | 'zCm' | 'rotationDeg' | 'widthCm' | 'depthCm'>,
  walls: Wall[],
  threshold = 10,
): Point {
  const corners = itemCorners(item)
  const c = { x: item.xCm, y: item.zCm }
  let best: { shift: Point; mag: number } | null = null
  for (const w of walls) {
    const len = wallLength(w)
    if (len < 1) continue
    const u = wallDir(w)
    const n = { x: -u.y, y: u.x }
    const s = (c.x - w.x1) * u.x + (c.y - w.y1) * u.y
    let hu = 0
    let hn = 0
    for (const p of corners) {
      hu = Math.max(hu, Math.abs((p.x - c.x) * u.x + (p.y - c.y) * u.y))
      hn = Math.max(hn, Math.abs((p.x - c.x) * n.x + (p.y - c.y) * n.y))
    }
    if (s + hu < -threshold || s - hu > len + threshold) continue
    const off = (c.x - w.x1) * n.x + (c.y - w.y1) * n.y
    const side = off >= 0 ? 1 : -1
    const desired = side * (w.thicknessCm / 2 + hn)
    const delta = desired - off
    const mag = Math.abs(delta)
    if (mag <= threshold && (!best || mag < best.mag)) {
      best = { shift: { x: n.x * delta, y: n.y * delta }, mag }
    }
  }
  return best ? { x: c.x + best.shift.x, y: c.y + best.shift.y } : c
}

// ---------------------------------------------------------------- openings / wall cutouts

export interface WallCutouts {
  /** openings that reach the floor (doors): carved from the bottom edge of the wall profile */
  notches: { x0: number; x1: number; top: number }[]
  /** openings with a sill (windows): rectangular holes */
  holes: { x0: number; x1: number; y0: number; y1: number }[]
}

function mergeIntervals(iv: [number, number][]): [number, number][] {
  const s = [...iv].sort((a, b) => a[0] - b[0])
  const out: [number, number][] = []
  for (const cur of s) {
    const last = out[out.length - 1]
    if (last && cur[0] <= last[1]) last[1] = Math.max(last[1], cur[1])
    else out.push([cur[0], cur[1]])
  }
  return out
}

/**
 * Compute door notches and window holes for a wall profile of length `length` and height `height`
 * (all centimeters, x measured from the wall start; callers add any end-extension offset).
 * Overlapping openings are merged; windows are clipped so they never overlap doors.
 */
export function computeWallCutouts(openings: Opening[], length: number, height: number): WallCutouts {
  const margin = 1
  const doors: [number, number][] = []
  const windows: { x0: number; x1: number; y0: number; y1: number }[] = []
  const doorTop = new Map<string, number>()
  for (const o of openings) {
    const x0 = clamp(o.offsetCm - o.widthCm / 2, margin, length - margin)
    const x1 = clamp(o.offsetCm + o.widthCm / 2, margin, length - margin)
    if (x1 - x0 < 2) continue
    const y0 = Math.max(0, o.sillCm)
    const y1 = Math.min(height - 1, o.sillCm + o.heightCm)
    if (y1 - y0 < 2) continue
    if (y0 <= 0.5) {
      doors.push([x0, x1])
      doorTop.set(`${x0}:${x1}`, y1)
    } else {
      windows.push({ x0, x1, y0, y1 })
    }
  }
  // Doors: merge overlaps; notch height = the tallest door in each merged group.
  const merged = mergeIntervals(doors)
  const notches = merged.map(([x0, x1]) => {
    let top = 0
    for (const [k, v] of doorTop) {
      const [a, b] = k.split(':').map(Number)
      if (a < x1 && b > x0) top = Math.max(top, v)
    }
    return { x0, x1, top }
  })
  // Windows: subtract door ranges, then merge overlaps between windows of the same sill/height only
  const holes: WallCutouts['holes'] = []
  for (const win of windows) {
    let pieces: [number, number][] = [[win.x0, win.x1]]
    for (const [dx0, dx1] of merged) {
      pieces = pieces.flatMap(([a, b]) => {
        if (dx1 <= a || dx0 >= b) return [[a, b] as [number, number]]
        const r: [number, number][] = []
        if (dx0 - a > 5) r.push([a, dx0 - 2])
        if (b - dx1 > 5) r.push([dx1 + 2, b])
        return r
      })
    }
    for (const [a, b] of pieces) if (b - a >= 5) holes.push({ x0: a, x1: b, y0: win.y0, y1: win.y1 })
  }
  // Remove overlapping window holes (keep earlier hole, trim later one)
  holes.sort((p, q) => p.x0 - q.x0)
  const clean: WallCutouts['holes'] = []
  for (const h of holes) {
    const prev = clean[clean.length - 1]
    if (prev && h.x0 < prev.x1 + 2) {
      if (h.x1 - (prev.x1 + 2) >= 5) clean.push({ ...h, x0: prev.x1 + 2 })
    } else clean.push(h)
  }
  return { notches, holes: clean }
}

/** Bounding box of walls + items (plan cm). Falls back to a default room-sized box. */
export function sceneBounds(scene: Pick<SceneState, 'walls' | 'placedItems'>): {
  minX: number; minY: number; maxX: number; maxY: number
} {
  const pts: Point[] = []
  for (const w of scene.walls) pts.push({ x: w.x1, y: w.y1 }, { x: w.x2, y: w.y2 })
  for (const it of scene.placedItems) pts.push(...itemCorners(it))
  if (!pts.length) return { minX: 0, minY: 0, maxX: 800, maxY: 600 }
  return {
    minX: Math.min(...pts.map((p) => p.x)),
    minY: Math.min(...pts.map((p) => p.y)),
    maxX: Math.max(...pts.map((p) => p.x)),
    maxY: Math.max(...pts.map((p) => p.y)),
  }
}

// ---------------------------------------------------------------- walk-through collision

/**
 * Convex polygons the walking camera cannot enter: wall segments (door gaps are left open,
 * windows stay solid) and furniture taller than 15 cm (rugs are walkable).
 */
export function buildWalkColliders(
  scene: Pick<SceneState, 'walls' | 'openings' | 'placedItems'>,
): Point[][] {
  const polys: Point[][] = []
  for (const w of scene.walls) {
    const len = wallLength(w)
    if (len < 1) continue
    const u = wallDir(w)
    const half = w.thicknessCm / 2
    const n = { x: -u.y * half, y: u.x * half }
    let solid: [number, number][] = [[-half, len + half]]
    for (const o of scene.openings) {
      if (o.wallId !== w.id || o.sillCm > 5) continue // windows block movement
      const d0 = o.offsetCm - o.widthCm / 2
      const d1 = o.offsetCm + o.widthCm / 2
      solid = solid.flatMap(([a, b]): [number, number][] => {
        if (d1 <= a || d0 >= b) return [[a, b]]
        const out: [number, number][] = []
        if (d0 > a) out.push([a, d0])
        if (d1 < b) out.push([d1, b])
        return out
      })
    }
    for (const [s, e] of solid) {
      if (e - s < 1) continue
      const p0 = { x: w.x1 + u.x * s, y: w.y1 + u.y * s }
      const p1 = { x: w.x1 + u.x * e, y: w.y1 + u.y * e }
      polys.push([
        { x: p0.x + n.x, y: p0.y + n.y },
        { x: p1.x + n.x, y: p1.y + n.y },
        { x: p1.x - n.x, y: p1.y - n.y },
        { x: p0.x - n.x, y: p0.y - n.y },
      ])
    }
  }
  for (const it of scene.placedItems) if (it.heightCm >= 15) polys.push(itemCorners(it))
  return polys
}

function closestOnPolygon(p: Point, poly: Point[]): { point: Point; distance: number } {
  let best = { point: poly[0], distance: Infinity }
  for (let i = 0; i < poly.length; i++) {
    const pr = projectOnSegment(p, poly[i], poly[(i + 1) % poly.length])
    if (pr.distance < best.distance) best = { point: pr.point, distance: pr.distance }
  }
  return best
}

/** Push a circle (center p, radius r) out of all convex polygons. */
export function resolveCircleCollisions(p: Point, r: number, polys: Point[][]): Point {
  let pos = p
  for (let pass = 0; pass < 3; pass++) {
    for (const poly of polys) {
      const inside = pointInPolygon(pos, poly)
      const { point: q, distance } = closestOnPolygon(pos, poly)
      if (!inside && distance >= r) continue
      const dx = inside ? q.x - pos.x : pos.x - q.x
      const dy = inside ? q.y - pos.y : pos.y - q.y
      const len = Math.hypot(dx, dy) || 1
      pos = { x: q.x + (dx / len) * r, y: q.y + (dy / len) * r }
    }
  }
  return pos
}

/**
 * Pick a sensible spawn point for the walk-through: the open spot (on a coarse grid) whose
 * 8 surrounding rays all hit a wall, preferring roomy spots far from walls — i.e. the middle of
 * the biggest enclosed room rather than the bounding-box center (which may be outside the plan).
 */
export function findWalkStart(
  wallPolys: Point[][],
  bounds: { minX: number; minY: number; maxX: number; maxY: number },
  fallback: Point,
): Point {
  if (wallPolys.length === 0) return fallback
  const dirs: Point[] = Array.from({ length: 8 }, (_, i) => ({
    x: Math.cos((i * Math.PI) / 4),
    y: Math.sin((i * Math.PI) / 4),
  }))
  const step = 40
  let best: { p: Point; score: number } | null = null
  for (let x = bounds.minX; x <= bounds.maxX; x += step) {
    for (let y = bounds.minY; y <= bounds.maxY; y += step) {
      const p = { x, y }
      if (wallPolys.some((poly) => pointInPolygon(p, poly))) continue
      let min = Infinity
      let sum = 0
      let enclosed = true
      for (const d of dirs) {
        let hit: number | null = null
        for (const poly of wallPolys) {
          const t = rayPolygon(p, d, poly)
          if (t !== null && (hit === null || t < hit)) hit = t
        }
        if (hit === null || hit > 1500) {
          enclosed = false
          break
        }
        min = Math.min(min, hit)
        sum += hit
      }
      if (!enclosed || min < 45) continue
      const score = min * 2 + sum / 8
      if (!best || score > best.score) best = { p, score }
    }
  }
  return best ? best.p : fallback
}
