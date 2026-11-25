import { describe, expect, it } from 'vitest'
import type { Category, Opening, PlacedItem, Product, Wall } from '../types'
import { planFurniture, placementsToItems } from './autoFurnish'
import type { FurnishRoom } from './autoFurnish'
import { buildBom } from './csv'
import { itemCorners, wallCorners, wallDir } from './geometry'
import { balconyRailings, detectRooms } from './rooms'
import { roomStats } from './roomTyping'

let n = 0
const wall = (x1: number, y1: number, x2: number, y2: number, t = 15): Wall => ({
  id: `w${++n}`,
  x1,
  y1,
  x2,
  y2,
  thicknessCm: t,
})
const rectWalls = (x0: number, y0: number, x1: number, y1: number): Wall[] => [
  wall(x0, y0, x1, y0),
  wall(x1, y0, x1, y1),
  wall(x1, y1, x0, y1),
  wall(x0, y1, x0, y0),
]

const product = (id: number, category: Category, w: number, d: number, h: number): Product => ({
  id,
  store_name: 'Test',
  product_url: `https://t/${id}`,
  title: `${category} ${id}`,
  category,
  price_ils: 1000,
  width_cm: w,
  depth_cm: d,
  height_cm: h,
  image_url: '',
  model_3d_url: null,
  model_status: 'none',
  model_error: null,
  updated_at: '',
})

const catalog: Partial<Record<Category, Product[]>> = {
  bed: [product(1, 'bed', 160, 200, 45), product(2, 'bed', 140, 200, 45)],
  wardrobe: [product(3, 'wardrobe', 160, 60, 220)],
  storage: [product(4, 'storage', 45, 40, 50)],
  desk: [product(5, 'desk', 120, 60, 75)],
  sofa: [product(6, 'sofa', 220, 90, 80)],
  tv_unit: [product(7, 'tv_unit', 180, 40, 50)],
  coffee_table: [product(8, 'coffee_table', 100, 50, 40)],
  dining_table: [product(9, 'dining_table', 180, 90, 75)],
  chair: [product(10, 'chair', 45, 50, 90)],
}

const overlaps = (a: { x: number; y: number }[], b: { x: number; y: number }[]): boolean => {
  for (const poly of [a, b])
    for (let i = 0; i < poly.length; i++) {
      const p = poly[i]
      const q = poly[(i + 1) % poly.length]
      const nx = -(q.y - p.y)
      const ny = q.x - p.x
      const proj = (pts: typeof a) => pts.map((v) => v.x * nx + v.y * ny)
      const pa = proj(a)
      const pb = proj(b)
      if (Math.max(...pa) <= Math.min(...pb) + 0.01 || Math.max(...pb) <= Math.min(...pa) + 0.01) return false
    }
  return true
}

/** The exact 3D wall shape: each wall mesh sticks out half its thickness past both ends. */
const meshShape = (w: Wall) => {
  const d = wallDir(w)
  const h = w.thicknessCm / 2
  return wallCorners({ ...w, x1: w.x1 - d.x * h, y1: w.y1 - d.y * h, x2: w.x2 + d.x * h, y2: w.y2 + d.y * h })
}

describe('room + balcony detection', () => {
  it('finds an enclosed room and splits two rooms by an inner wall', () => {
    const walls = [...rectWalls(0, 0, 700, 400), wall(400, 0, 400, 400)]
    const layout = detectRooms(walls)!
    expect(layout.rooms.length).toBe(2)
    const areas = layout.rooms.map((r) => r.areaCm2 / 10000).sort()
    expect(areas[0]).toBeGreaterThan(8)
    expect(areas[1]).toBeGreaterThan(10)
  })

  it('detects a balcony behind a patio door, with a railing on its open edge', () => {
    // 6x4 m room + a 3x2 m balcony walled on three sides (top, bottom, and the shared wall) and open to the right
    const room = rectWalls(0, 0, 600, 400)
    const balcony = [wall(600, 100, 900, 100), wall(600, 300, 900, 300)]
    const shared = room[1]
    const door: Opening = { id: 'o1', wallId: shared.id, kind: 'door', offsetCm: 200, widthCm: 180, heightCm: 210, sillCm: 0 }
    const layout = detectRooms([...room, ...balcony], [door])!
    const outdoor = layout.rooms.filter((r) => r.outdoor)
    expect(outdoor).toHaveLength(1)
    const m2 = outdoor[0].areaCm2 / 10000
    expect(m2).toBeGreaterThan(4)
    expect(m2).toBeLessThan(9)
    const rails = balconyRailings(layout)
    expect(rails.length).toBeGreaterThanOrEqual(1)
    expect(rails.some((s) => Math.abs(s.x1 - s.x2) < 1 && s.x1 > 850)).toBe(true) // the open right edge
  })

  it('does not turn an outside notch without a door into a balcony', () => {
    const room = rectWalls(0, 0, 600, 400)
    const notch = [wall(600, 100, 900, 100), wall(600, 300, 900, 300)]
    const layout = detectRooms([...room, ...notch], [])!
    expect(layout.rooms.some((r) => r.outdoor)).toBe(false)
  })
})

describe('auto-furnish', () => {
  const walls = [...rectWalls(0, 0, 700, 420), wall(420, 0, 420, 420, 10)] // bedroom 4.2 x 4.2 m | bathroom 2.8 x 4.2 m
  const door: Opening = { id: 'd1', wallId: walls[4].id, kind: 'door', offsetCm: 300, widthCm: 80, heightCm: 210, sillCm: 0 }
  const layout = detectRooms(walls, [door])!
  const stats = roomStats(layout, walls, [door])
  const byX = [...layout.rooms].sort((a, b) => a.cx - b.cx)
  const rooms: FurnishRoom[] = [
    { id: byX[0].id, kind: 'master', ...pick(stats[byX[0].id], byX[0].areaCm2) },
    { id: byX[1].id, kind: 'bathroom', ...pick(stats[byX[1].id], byX[1].areaCm2) },
  ]
  function pick(s: { minX: number; minY: number; maxX: number; maxY: number }, area: number) {
    return { areaM2: area / 10000, minX: s.minX, minY: s.minY, maxX: s.maxX, maxY: s.maxY }
  }

  const placements = planFurniture(layout, rooms, walls, [door], catalog)
  const items: PlacedItem[] = placementsToItems(placements)

  it('furnishes a bedroom with a bed, bedside tables and a wardrobe', () => {
    const cats = items.filter((i) => !i.fixture).map((i) => i.category)
    expect(cats).toContain('bed')
    expect(cats).toContain('wardrobe')
    expect(cats.filter((c) => c === 'storage').length).toBe(2)
  })

  it('puts bathroom fixtures in the bathroom, flagged as preview-only with no price', () => {
    const fixtures = items.filter((i) => i.fixture)
    const kinds = fixtures.map((f) => f.fixture)
    expect(kinds).toContain('toilet')
    expect(kinds).toContain('sink')
    expect(kinds.some((k) => k === 'bathtub' || k === 'shower')).toBe(true)
    expect(fixtures.every((f) => f.priceIls === 0 && f.productId === 0 && f.storeName === '')).toBe(true)
  })

  it('never lets an item overlap a wall (including the wall ends) or another item', () => {
    const shapes = walls.map(meshShape)
    const polys = items.map((i) => itemCorners(i))
    items.forEach((it, i) => {
      for (const ws of shapes) expect(overlaps(polys[i], ws), `${it.title} overlaps a wall`).toBe(false)
      for (let j = i + 1; j < items.length; j++)
        expect(overlaps(polys[i], polys[j]), `${it.title} overlaps ${items[j].title}`).toBe(false)
    })
  })

  it('keeps fixtures out of the shopping list', () => {
    const bom = buildBom(items)
    expect(bom.every((l) => l.productId !== 0)).toBe(true)
    expect(bom.reduce((s, l) => s + l.qty, 0)).toBe(items.filter((i) => !i.fixture).length)
  })
})
