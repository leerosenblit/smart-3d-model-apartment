// Procedural floor materials, painted with the 2D canvas API (no image assets needed).
// Every pattern tile is drawn at 1 pixel = 1 cm so it can be scaled to any floor texture resolution.
import type { FloorMaterialId } from '../types'

export interface FloorMaterial {
  id: FloorMaterialId
  label: string
  /** physical size of one repeating pattern tile in cm */
  tileCm: number
  roughness: number
}

export const FLOOR_MATERIALS: FloorMaterial[] = [
  { id: 'oak', label: 'פרקט אלון', tileCm: 240, roughness: 0.55 },
  { id: 'walnut', label: 'פרקט אגוז', tileCm: 240, roughness: 0.5 },
  { id: 'tile_white', label: 'אריחים לבנים', tileCm: 120, roughness: 0.35 },
  { id: 'tile_beige', label: 'אריחים בז׳', tileCm: 90, roughness: 0.4 },
  { id: 'concrete', label: 'בטון מוחלק', tileCm: 256, roughness: 0.8 },
  { id: 'carpet', label: 'שטיח קיר-לקיר', tileCm: 128, roughness: 1 },
]

export const materialInfo = (id: FloorMaterialId): FloorMaterial =>
  FLOOR_MATERIALS.find((m) => m.id === id) ?? FLOOR_MATERIALS[0]

/** Small rooms are usually bathrooms/toilets → tile; everything else → oak parquet. */
export const autoMaterial = (areaCm2: number): FloorMaterialId => (areaCm2 < 60000 ? 'tile_white' : 'oak')

function rng(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function makeCanvas(w: number, h: number): [HTMLCanvasElement, CanvasRenderingContext2D] {
  const c = document.createElement('canvas')
  c.width = w
  c.height = h
  return [c, c.getContext('2d')!]
}

function speckle(ctx: CanvasRenderingContext2D, w: number, h: number, density: number, rand: () => number, a = 0.07) {
  const n = Math.floor(w * h * density)
  for (let i = 0; i < n; i++) {
    const dark = rand() < 0.5
    ctx.fillStyle = dark ? `rgba(0,0,0,${a * rand()})` : `rgba(255,255,255,${a * rand()})`
    ctx.fillRect(Math.floor(rand() * w), Math.floor(rand() * h), 1, 1)
  }
}

function paintPlanks(hue: number, sat: number, light: number, seed: number): HTMLCanvasElement {
  const S = 240
  const [c, ctx] = makeCanvas(S, S)
  const rand = rng(seed)
  const rowH = 15
  for (let row = 0; row < S / rowH; row++) {
    // plank lengths that wrap exactly to S so the tile repeats seamlessly
    const lens: number[] = []
    let sum = 0
    while (sum < S) {
      const l = Math.min(S - sum, 70 + Math.floor(rand() * 60))
      lens.push(S - sum - l < 25 ? S - sum : l)
      sum += lens[lens.length - 1]
    }
    let x = 0
    for (const len of lens) {
      const y = row * rowH
      const l = light + (rand() - 0.5) * 9
      ctx.fillStyle = `hsl(${hue + (rand() - 0.5) * 5}, ${sat + (rand() - 0.5) * 6}%, ${l}%)`
      ctx.fillRect(x, y, len, rowH)
      // wood grain
      for (let g = 0; g < 6; g++) {
        const gy = y + 1 + rand() * (rowH - 2)
        ctx.strokeStyle = `rgba(70,40,15,${0.07 + rand() * 0.13})`
        ctx.lineWidth = 0.6 + rand() * 0.6
        ctx.beginPath()
        ctx.moveTo(x, gy)
        const segs = 4
        for (let k = 1; k <= segs; k++) ctx.lineTo(x + (len * k) / segs, gy + (rand() - 0.5) * 1.6)
        ctx.stroke()
      }
      // soft highlight along the top of each plank
      const grad = ctx.createLinearGradient(0, y, 0, y + rowH)
      grad.addColorStop(0, 'rgba(255,255,255,0.10)')
      grad.addColorStop(0.5, 'rgba(255,255,255,0)')
      grad.addColorStop(1, 'rgba(0,0,0,0.08)')
      ctx.fillStyle = grad
      ctx.fillRect(x, y, len, rowH)
      // joints
      ctx.fillStyle = 'rgba(40,25,10,0.5)'
      ctx.fillRect(x, y, 1, rowH)
      x += len
    }
    ctx.fillStyle = 'rgba(40,25,10,0.38)'
    ctx.fillRect(0, row * rowH, S, 1)
  }
  return c
}

function paintTiles(tileCm: number, count: number, base: [number, number, number], grout: string, seed: number): HTMLCanvasElement {
  const S = tileCm * count
  const [c, ctx] = makeCanvas(S, S)
  const rand = rng(seed)
  for (let i = 0; i < count; i++)
    for (let j = 0; j < count; j++) {
      const k = 1 + (rand() - 0.5) * 0.045
      ctx.fillStyle = `rgb(${Math.round(base[0] * k)},${Math.round(base[1] * k)},${Math.round(base[2] * k)})`
      ctx.fillRect(i * tileCm, j * tileCm, tileCm, tileCm)
      const grad = ctx.createLinearGradient(i * tileCm, j * tileCm, (i + 1) * tileCm, (j + 1) * tileCm)
      grad.addColorStop(0, 'rgba(255,255,255,0.10)')
      grad.addColorStop(1, 'rgba(0,0,0,0.05)')
      ctx.fillStyle = grad
      ctx.fillRect(i * tileCm, j * tileCm, tileCm, tileCm)
    }
  speckle(ctx, S, S, 0.12, rand, 0.06)
  ctx.fillStyle = grout
  for (let i = 0; i <= count; i++) {
    ctx.fillRect(i * tileCm - 0.9, 0, 1.8, S)
    ctx.fillRect(0, i * tileCm - 0.9, S, 1.8)
  }
  return c
}

function paintConcrete(): HTMLCanvasElement {
  const S = 256
  const [c, ctx] = makeCanvas(S, S)
  const rand = rng(7)
  ctx.fillStyle = '#b8b8b4'
  ctx.fillRect(0, 0, S, S)
  for (let i = 0; i < 40; i++) {
    const x = rand() * S
    const y = rand() * S
    const r = 25 + rand() * 60
    for (const [dx, dy] of [[0, 0], [S, 0], [-S, 0], [0, S], [0, -S]]) {
      const g = ctx.createRadialGradient(x + dx, y + dy, 0, x + dx, y + dy, r)
      const dark = rand() < 0.5
      g.addColorStop(0, dark ? 'rgba(60,60,58,0.07)' : 'rgba(255,255,255,0.08)')
      g.addColorStop(1, 'rgba(0,0,0,0)')
      ctx.fillStyle = g
      ctx.fillRect(0, 0, S, S)
    }
  }
  speckle(ctx, S, S, 0.25, rand, 0.1)
  return c
}

function paintCarpet(): HTMLCanvasElement {
  const S = 128
  const [c, ctx] = makeCanvas(S, S)
  const rand = rng(11)
  ctx.fillStyle = '#8d939b'
  ctx.fillRect(0, 0, S, S)
  speckle(ctx, S, S, 0.9, rand, 0.22)
  return c
}

const tileCache = new Map<FloorMaterialId, HTMLCanvasElement>()

/** Repeating pattern tile, 1 px = 1 cm. */
export function patternTile(id: FloorMaterialId): HTMLCanvasElement {
  let t = tileCache.get(id)
  if (!t) {
    switch (id) {
      case 'oak': t = paintPlanks(33, 52, 62, 101); break
      case 'walnut': t = paintPlanks(22, 36, 29, 202); break
      case 'tile_white': t = paintTiles(60, 2, [236, 238, 241], 'rgba(150,155,162,0.75)', 5); break
      case 'tile_beige': t = paintTiles(45, 2, [218, 203, 180], 'rgba(150,135,110,0.75)', 9); break
      case 'concrete': t = paintConcrete(); break
      default: t = paintCarpet()
    }
    tileCache.set(id, t)
  }
  return t
}

const swatchCache = new Map<FloorMaterialId, string>()
/** Small square preview (data URL) for pickers. */
export function swatchUrl(id: FloorMaterialId, size = 64): string {
  let u = swatchCache.get(id)
  if (!u) {
    const [c, ctx] = makeCanvas(size, size)
    const tile = patternTile(id)
    const pat = ctx.createPattern(tile, 'repeat')!
    ctx.scale(size / 120, size / 120) // show ~1.2 m of floor
    ctx.fillStyle = pat
    ctx.fillRect(0, 0, 120, 120)
    u = c.toDataURL('image/png')
    swatchCache.set(id, u)
  }
  return u
}
