// Builds ONE canvas texture covering the whole plan, with each detected room painted in its
// floor material. Shared by the 2D editor (as an <image>) and the 3D viewer (as a map).
import type { FloorMaterialId, RoomStyle, Wall } from '../types'
import { autoMaterial, materialInfo, patternTile } from './floorMaterials'
import { boxPass, detectRooms, styleIndexForRoom } from './rooms'
import type { RoomInfo, RoomLayout } from './rooms'

export interface ResolvedRoom {
  room: RoomInfo
  material: FloorMaterialId
  name: string
  areaM2: number
  styleIndex: number
}

export interface FloorResult {
  layout: RoomLayout
  rooms: ResolvedRoom[]
  canvas: HTMLCanvasElement
  /** plan-space rectangle the canvas covers (cm) */
  originX: number
  originY: number
  widthCm: number
  heightCm: number
}

const MAX_TEXTURE = 2048
let cache: { key: string; value: FloorResult | null } | null = null

export function computeFloor(walls: Wall[], styles: RoomStyle[]): FloorResult | null {
  const key = JSON.stringify([walls.map((w) => [w.x1, w.y1, w.x2, w.y2, w.thicknessCm]), styles])
  if (cache?.key === key) return cache.value
  const value = build(walls, styles)
  cache = { key, value }
  return value
}

function build(walls: Wall[], styles: RoomStyle[]): FloorResult | null {
  const layout = detectRooms(walls)
  if (!layout) return null
  const { w, h, cell } = layout

  const rooms: ResolvedRoom[] = layout.rooms.map((room) => {
    const si = styleIndexForRoom(layout, styles, room.id)
    const st = si >= 0 ? styles[si] : undefined
    return {
      room,
      material: st?.material ?? autoMaterial(room.areaCm2),
      name: st?.name?.trim() || `חדר ${room.id + 1}`,
      areaM2: room.areaCm2 / 10000,
      styleIndex: si,
    }
  })

  const widthCm = w * cell
  const heightCm = h * cell
  const ppc = Math.min(1, MAX_TEXTURE / Math.max(widthCm, heightCm))
  const cw = Math.max(1, Math.round(widthCm * ppc))
  const ch = Math.max(1, Math.round(heightCm * ppc))
  const canvas = document.createElement('canvas')
  canvas.width = cw
  canvas.height = ch
  const ctx = canvas.getContext('2d')!

  const groups = new Map<FloorMaterialId, Set<number>>()
  for (const r of rooms) {
    if (!groups.has(r.material)) groups.set(r.material, new Set())
    groups.get(r.material)!.add(r.room.id)
  }

  for (const [material, ids] of groups) {
    // room mask, grown by 2 cells so the floor tucks under the walls (no gaps at the edges)
    let mask = new Uint8Array(w * h)
    for (let i = 0; i < mask.length; i++) if (layout.labels[i] >= 0 && ids.has(layout.labels[i])) mask[i] = 1
    mask = boxPass(boxPass(mask, w, h, 2, true, true), w, h, 2, false, true)
    const mc = document.createElement('canvas')
    mc.width = w
    mc.height = h
    const mctx = mc.getContext('2d')!
    const img = mctx.createImageData(w, h)
    for (let i = 0; i < mask.length; i++) if (mask[i]) img.data[i * 4 + 3] = 255
    mctx.putImageData(img, 0, 0)

    const tmp = document.createElement('canvas')
    tmp.width = cw
    tmp.height = ch
    const tctx = tmp.getContext('2d')!
    tctx.imageSmoothingEnabled = true
    tctx.drawImage(mc, 0, 0, cw, ch)
    tctx.globalCompositeOperation = 'source-in'
    tctx.save()
    tctx.scale(ppc, ppc)
    tctx.fillStyle = tctx.createPattern(patternTile(material), 'repeat')!
    tctx.fillRect(0, 0, widthCm, heightCm)
    tctx.restore()
    ctx.drawImage(tmp, 0, 0)
  }
  return { layout, rooms, canvas, originX: layout.minX, originY: layout.minY, widthCm, heightCm }
}

/** Translucent highlight image (data URL) for one room, aligned with the floor canvas rectangle. */
export function roomHighlightUrl(layout: RoomLayout, roomId: number, rgba = 'rgba(47,125,225,0.28)'): string {
  const mc = document.createElement('canvas')
  mc.width = layout.w
  mc.height = layout.h
  const ctx = mc.getContext('2d')!
  const img = ctx.createImageData(layout.w, layout.h)
  const m = /rgba\((\d+),(\d+),(\d+),([\d.]+)\)/.exec(rgba) ?? ['', '47', '125', '225', '0.28']
  for (let i = 0; i < layout.labels.length; i++) {
    if (layout.labels[i] !== roomId) continue
    img.data[i * 4] = Number(m[1])
    img.data[i * 4 + 1] = Number(m[2])
    img.data[i * 4 + 2] = Number(m[3])
    img.data[i * 4 + 3] = Math.round(Number(m[4]) * 255)
  }
  ctx.putImageData(img, 0, 0)
  return mc.toDataURL('image/png')
}

export { materialInfo }
