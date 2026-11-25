// Auto-furnishing: picks suitable catalog products per room type and places them like a person would —
// beds with the headboard on a wall, wardrobes in corners, the sofa facing the TV, a dining table with chairs
// in the roomiest spot — never blocking doors and never overlapping. All coordinates are plan centimeters.
import type { Category, Opening, PlacedItem, Point, Product, RoomKind, Wall } from '../types'
import { degToRad, itemCorners, wallDir } from './geometry'
import { uid } from './format'
import { roomAt } from './rooms'
import type { RoomLayout } from './rooms'

export interface FurnishRoom {
  id: number
  kind: RoomKind
  areaM2: number
  minX: number
  minY: number
  maxX: number
  maxY: number
}

export interface Placement {
  product: Product
  xCm: number
  zCm: number
  rotationDeg: number
}

type Catalog = Partial<Record<Category, Product[]>>

const STEP = 10
const GAP = 3 // cm of breathing room added around every footprint when testing
const rotations = [0, 90, 180, 270]

// ------------------------------------------------------------------ geometry helpers

function overlaps(a: Point[], b: Point[]): boolean {
  for (const poly of [a, b])
    for (let i = 0; i < poly.length; i++) {
      const p = poly[i]
      const q = poly[(i + 1) % poly.length]
      const nx = -(q.y - p.y)
      const ny = q.x - p.x
      let aMin = Infinity, aMax = -Infinity, bMin = Infinity, bMax = -Infinity
      for (const v of a) {
        const d = v.x * nx + v.y * ny
        aMin = Math.min(aMin, d)
        aMax = Math.max(aMax, d)
      }
      for (const v of b) {
        const d = v.x * nx + v.y * ny
        bMin = Math.min(bMin, d)
        bMax = Math.max(bMax, d)
      }
      if (aMax <= bMin || bMax <= aMin) return false
    }
  return true
}

const frontOf = (rotDeg: number): Point => {
  const a = degToRad(rotDeg)
  return { x: -Math.sin(a), y: Math.cos(a) } // local +z in plan space
}

class Room {
  placed: { poly: Point[]; product: Product; xCm: number; zCm: number; rotationDeg: number }[] = []
  doorZones: Point[][] = []
  constructor(
    private layout: RoomLayout,
    readonly info: FurnishRoom,
  ) {}

  inside(x: number, y: number): boolean {
    return roomAt(this.layout, x, y) === this.info.id
  }

  footprint(x: number, z: number, rot: number, w: number, d: number): Point[] {
    return itemCorners({ xCm: x, zCm: z, rotationDeg: rot, widthCm: w + GAP * 2, depthCm: d + GAP * 2 })
  }

  /** Is the whole (slightly inflated) footprint inside the room, off the door zones and clear of placed items? */
  fits(x: number, z: number, rot: number, w: number, d: number, ignore?: Point[]): boolean {
    const poly = this.footprint(x, z, rot, w, d)
    const pts: Point[] = [...poly, { x, y: z }]
    for (let i = 0; i < 4; i++) pts.push({ x: (poly[i].x + poly[(i + 1) % 4].x) / 2, y: (poly[i].y + poly[(i + 1) % 4].y) / 2 })
    if (!pts.every((p) => this.inside(p.x, p.y))) return false
    if (this.doorZones.some((z2) => overlaps(poly, z2))) return false
    return !this.placed.some((p) => p.poly !== ignore && overlaps(poly, p.poly))
  }

  /** Free distance from (x, y) along dir while staying inside the room (capped). */
  free(x: number, y: number, dir: Point, max = 500): number {
    let t = 0
    while (t < max && this.inside(x + dir.x * (t + STEP), y + dir.y * (t + STEP))) t += STEP
    return t
  }

  /** True when the back (-z) edge of the item sits against a wall. */
  backOnWall(x: number, z: number, rot: number, d: number): boolean {
    const f = frontOf(rot)
    const reach = d / 2 + GAP + STEP + 2 // window wider than the scan step: no wall-flush spot is missed between samples
    const bx = x - f.x * reach
    const by = z - f.y * reach
    return !this.inside(bx, by)
  }

  add(product: Product, x: number, z: number, rot: number): void {
    this.placed.push({
      poly: this.footprint(x, z, rot, product.width_cm, product.depth_cm),
      product,
      xCm: x,
      zCm: z,
      rotationDeg: rot,
    })
  }

  candidates(w: number, d: number, rotSet = rotations): { x: number; z: number; rot: number }[] {
    const out: { x: number; z: number; rot: number }[] = []
    const { minX, minY, maxX, maxY } = this.info
    for (let x = minX; x <= maxX; x += STEP)
      for (let z = minY; z <= maxY; z += STEP)
        for (const rot of rotSet) if (this.fits(x, z, rot, w, d)) out.push({ x, z, rot })
    return out
  }
}

// ------------------------------------------------------------------ product choice

function pick(
  catalog: Catalog,
  cat: Category,
  ok: (p: Product) => boolean,
  target: (p: Product) => number,
  variant = 0,
): Product | null {
  const list = (catalog[cat] ?? []).filter(ok).sort((a, b) => target(a) - target(b))
  if (!list.length) return null
  const top = list.slice(0, Math.min(6, list.length))
  return top[variant % top.length]
}

const near = (v: number, goal: number) => Math.abs(v - goal)

// ------------------------------------------------------------------ per-room furnishing

function furnishBedroom(r: Room, catalog: Catalog, variant: number): void {
  const master = r.info.kind === 'master'
  const bedW = master ? 180 : r.info.areaM2 >= 11 ? 160 : 140
  const bed = pick(
    catalog,
    'bed',
    (p) => p.width_cm >= bedW - 25 && p.width_cm <= bedW + 25 && p.depth_cm <= 222 && p.depth_cm >= 185 && p.height_cm <= 140,
    (p) => near(p.width_cm, bedW) + near(p.depth_cm, 205) / 2,
    variant,
  )
  let bedPose: { x: number; z: number; rot: number } | null = null
  if (bed) {
    const doors = r.doorZones.map((z) => ({ x: z.reduce((s, p) => s + p.x, 0) / z.length, y: z.reduce((s, p) => s + p.y, 0) / z.length }))
    let best = -Infinity
    for (const c of r.candidates(bed.width_cm, bed.depth_cm)) {
      if (!r.backOnWall(c.x, c.z, c.rot, bed.depth_cm)) continue
      const right = frontOf(c.rot)
      const lat = { x: -right.y, y: right.x }
      const L = r.free(c.x, c.z, lat, 150)
      const R = r.free(c.x, c.z, { x: -lat.x, y: -lat.y }, 150)
      const clearance = r.free(c.x, c.z, right, 400) - bed.depth_cm / 2
      const doorDist = doors.length ? Math.min(...doors.map((d) => Math.hypot(d.x - c.x, d.y - c.z))) : 300
      const score = Math.min(doorDist, 400) * 0.5 + Math.min(L - bed.width_cm / 2, R - bed.width_cm / 2, 60) * 3 - Math.abs(L - R) * 0.6 + Math.min(clearance, 200) * 0.4
      if (score > best) {
        best = score
        bedPose = c
      }
    }
    if (bedPose) r.add(bed, bedPose.x, bedPose.z, bedPose.rot)
  }

  // bedside tables on either side of the bed
  if (bed && bedPose) {
    const table = pick(catalog, 'storage', (p) => p.width_cm >= 35 && p.width_cm <= 60 && p.depth_cm <= 50 && p.height_cm >= 35 && p.height_cm <= 65, (p) => near(p.width_cm, 45), variant)
    if (table) {
      const f = frontOf(bedPose.rot)
      const lat = { x: -f.y, y: f.x }
      for (const side of [1, -1]) {
        const off = bed.width_cm / 2 + table.width_cm / 2 + GAP * 2 + 2
        const back = bed.depth_cm / 2 - table.depth_cm / 2
        const x = bedPose.x + lat.x * off * side - f.x * back
        const z = bedPose.z + lat.y * off * side - f.y * back
        if (r.fits(x, z, bedPose.rot, table.width_cm, table.depth_cm)) r.add(table, x, z, bedPose.rot)
      }
    }
  }

  // wardrobe: corner or wall, door zone and bed respected
  const wardrobe = pick(
    catalog,
    'wardrobe',
    (p) => p.width_cm >= 100 && p.width_cm <= 260 && p.depth_cm <= 68 && p.height_cm >= 190,
    (p) => near(p.width_cm, master ? 220 : 160) + near(p.depth_cm, 60),
    variant,
  )
  if (wardrobe) {
    let best = -Infinity
    let pose: { x: number; z: number; rot: number } | null = null
    for (const c of r.candidates(wardrobe.width_cm, wardrobe.depth_cm)) {
      if (!r.backOnWall(c.x, c.z, c.rot, wardrobe.depth_cm)) continue
      const f = frontOf(c.rot)
      const lat = { x: -f.y, y: f.x }
      const L = r.free(c.x, c.z, lat, 150) - wardrobe.width_cm / 2
      const R = r.free(c.x, c.z, { x: -lat.x, y: -lat.y }, 150) - wardrobe.width_cm / 2
      const front = r.free(c.x, c.z, f, 300) - wardrobe.depth_cm / 2
      if (front < 85) continue
      const score = -Math.min(L, R) * 2 + Math.min(front, 200) * 0.3
      if (score > best) {
        best = score
        pose = c
      }
    }
    if (pose) r.add(wardrobe, pose.x, pose.z, pose.rot)
  }

  // desk for rooms with space to spare (kids / home office feel)
  if (r.info.areaM2 >= 9 && !master) {
    const desk = pick(catalog, 'desk', (p) => p.width_cm >= 100 && p.width_cm <= 150 && p.depth_cm <= 75, (p) => near(p.width_cm, 120), variant)
    if (desk) {
      const c = r.candidates(desk.width_cm, desk.depth_cm).filter((q) => r.backOnWall(q.x, q.z, q.rot, desk.depth_cm))
      const pose = c.sort((a, b) => r.free(b.x, b.z, frontOf(b.rot), 300) - r.free(a.x, a.z, frontOf(a.rot), 300))[0]
      if (pose) r.add(desk, pose.x, pose.z, pose.rot)
    }
  }
}

function furnishLiving(r: Room, catalog: Catalog, variant: number): void {
  const tv = pick(catalog, 'tv_unit', (p) => p.width_cm >= 130 && p.width_cm <= 220 && p.depth_cm <= 50 && p.height_cm <= 70, (p) => near(p.width_cm, 180), variant)
  let tvPose: { x: number; z: number; rot: number } | null = null
  if (tv) {
    let best = -Infinity
    for (const c of r.candidates(tv.width_cm, tv.depth_cm)) {
      if (!r.backOnWall(c.x, c.z, c.rot, tv.depth_cm)) continue
      const f = frontOf(c.rot)
      const lat = { x: -f.y, y: f.x }
      const depthFree = r.free(c.x, c.z, f, 600)
      const L = r.free(c.x, c.z, lat, 200)
      const R = r.free(c.x, c.z, { x: -lat.x, y: -lat.y }, 200)
      const score = Math.min(depthFree, 450) - Math.abs(L - R) * 0.8
      if (depthFree >= 280 && score > best) {
        best = score
        tvPose = c
      }
    }
    if (tvPose) r.add(tv, tvPose.x, tvPose.z, tvPose.rot)
  }

  const sofa = pick(catalog, 'sofa', (p) => p.width_cm >= 190 && p.width_cm <= 260 && p.depth_cm <= 110, (p) => near(p.width_cm, 220), variant)
  let sofaPose: { x: number; z: number; rot: number } | null = null
  if (sofa && tv && tvPose) {
    const f = frontOf(tvPose.rot)
    const rot = (tvPose.rot + 180) % 360
    let bestErr = Infinity
    for (let dist = 230; dist <= 360; dist += STEP) {
      for (let lateral = 0; lateral <= 60; lateral += STEP) {
        for (const sgn of [1, -1]) {
          const lat = { x: -f.y * sgn, y: f.x * sgn }
          const x = tvPose.x + f.x * dist + lat.x * lateral
          const z = tvPose.z + f.y * dist + lat.y * lateral
          if (!r.fits(x, z, rot, sofa.width_cm, sofa.depth_cm)) continue
          const err = Math.abs(dist - 280) + lateral
          if (err < bestErr) {
            bestErr = err
            sofaPose = { x, z, rot }
          }
        }
      }
    }
    if (sofaPose) r.add(sofa, sofaPose.x, sofaPose.z, sofaPose.rot)
  }

  const table = pick(catalog, 'coffee_table', (p) => p.width_cm >= 80 && p.width_cm <= 130 && p.depth_cm <= 75 && p.height_cm <= 55, (p) => near(p.width_cm, 100), variant)
  if (table && tvPose && sofaPose && tv && sofa) {
    const f = frontOf(tvPose.rot)
    const sofaDist = Math.hypot(sofaPose.x - tvPose.x, sofaPose.z - tvPose.z)
    const mid = sofaDist - sofa.depth_cm / 2 - 55 - table.depth_cm / 2
    if (r.fits(tvPose.x + f.x * mid, tvPose.z + f.y * mid, tvPose.rot, table.width_cm, table.depth_cm))
      r.add(table, tvPose.x + f.x * mid, tvPose.z + f.y * mid, tvPose.rot)
  }

  // dining set in the roomiest remaining spot
  const dining = pick(catalog, 'dining_table', (p) => p.width_cm >= 150 && p.width_cm <= 230 && p.depth_cm >= 80 && p.depth_cm <= 110 && p.height_cm >= 70 && p.height_cm <= 80, (p) => near(p.width_cm, 180), variant)
  const chair = pick(catalog, 'chair', (p) => p.width_cm <= 56 && p.depth_cm <= 62 && p.height_cm >= 75 && p.height_cm <= 110, (p) => near(p.width_cm, 45), variant)
  if (dining && chair) {
    let best = -Infinity
    let pose: { x: number; z: number; rot: number } | null = null
    // table plus ~55 cm of chair space on the long sides and ~30 cm at the ends
    for (const c of r.candidates(dining.width_cm + 60, dining.depth_cm + 110, [0, 90])) {
      if (!r.fits(c.x, c.z, c.rot, dining.width_cm, dining.depth_cm)) continue
      const room = Math.min(
        r.free(c.x, c.z, { x: 1, y: 0 }, 200), r.free(c.x, c.z, { x: -1, y: 0 }, 200),
        r.free(c.x, c.z, { x: 0, y: 1 }, 200), r.free(c.x, c.z, { x: 0, y: -1 }, 200),
      )
      if (room > best) {
        best = room
        pose = c
      }
    }
    if (pose) {
      r.add(dining, pose.x, pose.z, pose.rot)
      const tablePoly = r.placed[r.placed.length - 1].poly
      const f = frontOf(pose.rot)
      const along = { x: -f.y, y: f.x }
      const perChair = chair.width_cm + 8
      const n = Math.max(2, Math.min(4, Math.floor((dining.width_cm - 10) / perChair)))
      for (const side of [1, -1]) {
        for (let i = 0; i < n; i++) {
          const t = ((i + 0.5) / n - 0.5) * (dining.width_cm - perChair * 0.4)
          const off = (dining.depth_cm / 2 + chair.depth_cm / 2 - 14) * side
          const x = pose.x + along.x * t + f.x * off
          const z = pose.z + along.y * t + f.y * off
          const rot = (pose.rot + (side === 1 ? 180 : 0)) % 360 // chairs face the table
          if (r.fits(x, z, rot, chair.width_cm, chair.depth_cm, tablePoly)) r.add(chair, x, z, rot)
        }
      }
    }
  }
}

// ------------------------------------------------------------------ public API

function doorZones(layout: RoomLayout, room: FurnishRoom, walls: Wall[], openings: Opening[]): Point[][] {
  const zones: Point[][] = []
  for (const o of openings) {
    if (o.kind !== 'door') continue
    const wall = walls.find((w) => w.id === o.wallId)
    if (!wall) continue
    const d = wallDir(wall)
    const c = { x: wall.x1 + d.x * o.offsetCm, y: wall.y1 + d.y * o.offsetCm }
    for (const side of [1, -1]) {
      const n = { x: -d.y * side, y: d.x * side }
      const probe = { x: c.x + n.x * (wall.thicknessCm / 2 + 20), y: c.y + n.y * (wall.thicknessCm / 2 + 20) }
      if (roomAt(layout, probe.x, probe.y) !== room.id) continue
      // swing/clear zone: door width + 20 wide, 90 deep, on this room's side
      const depth = 90
      const cx = c.x + n.x * (wall.thicknessCm / 2 + depth / 2)
      const cy = c.y + n.y * (wall.thicknessCm / 2 + depth / 2)
      const ang = (Math.atan2(d.y, d.x) * 180) / Math.PI
      zones.push(itemCorners({ xCm: cx, zCm: cy, rotationDeg: ang, widthCm: o.widthCm + 20, depthCm: depth }))
    }
  }
  return zones
}

/** Plan placements for every furnishable room. Pure: no store / network access. */
export function planFurniture(
  layout: RoomLayout,
  rooms: FurnishRoom[],
  walls: Wall[],
  openings: Opening[],
  catalog: Catalog,
): Placement[] {
  const out: Placement[] = []
  let variant = 0
  const order = [...rooms].sort((a, b) => b.areaM2 - a.areaM2)
  for (const info of order) {
    const bedroom = info.kind === 'bedroom' || info.kind === 'master' || info.kind === 'kids'
    if (!bedroom && info.kind !== 'living') continue
    const room = new Room(layout, info)
    room.doorZones = doorZones(layout, info, walls, openings)
    if (info.kind === 'living') furnishLiving(room, catalog, variant)
    else furnishBedroom(room, catalog, variant)
    variant++
    for (const p of room.placed) out.push({ product: p.product, xCm: Math.round(p.xCm), zCm: Math.round(p.zCm), rotationDeg: p.rotationDeg })
  }
  return out
}

export function placementsToItems(placements: Placement[]): PlacedItem[] {
  return placements.map(({ product: p, xCm, zCm, rotationDeg }) => ({
    id: uid('item'),
    productId: p.id,
    xCm,
    zCm,
    rotationDeg,
    title: p.title,
    storeName: p.store_name,
    productUrl: p.product_url,
    priceIls: p.price_ils,
    category: p.category,
    widthCm: p.width_cm,
    depthCm: p.depth_cm,
    heightCm: p.height_cm,
    imageUrl: p.image_url,
  }))
}
