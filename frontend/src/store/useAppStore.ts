import { create } from 'zustand'
import type {
  DetectedWall,
  ModelState,
  Opening,
  OpeningKind,
  PlacedItem,
  Product,
  RoomStyle,
  SceneState,
  Selection,
  Tool,
  ViewMode,
  Wall,
} from '../types'
import { uid } from '../utils/format'
import { wallLength } from '../utils/geometry'

export const DEFAULT_CEILING_CM = 270
export const DEFAULT_WALL_THICKNESS_CM = 15
const HISTORY_LIMIT = 100

export const OPENING_DEFAULTS: Record<OpeningKind, { widthCm: number; heightCm: number; sillCm: number }> = {
  door: { widthCm: 90, heightCm: 210, sillCm: 0 },
  window: { widthCm: 120, heightCm: 120, sillCm: 90 },
}

export interface Toast {
  id: string
  message: string
  kind: 'info' | 'error' | 'success'
}

export interface CatalogFilters {
  search: string
  category: string
  maxWidthCm: string
  maxPriceIls: string
  sortBy: string
}

const emptyScene = (): SceneState => ({
  ceilingHeightCm: DEFAULT_CEILING_CM,
  walls: [],
  openings: [],
  placedItems: [],
  roomStyles: [],
})

const sceneOf = (s: AppState): SceneState => ({
  ceilingHeightCm: s.ceilingHeightCm,
  walls: s.walls,
  openings: s.openings,
  placedItems: s.placedItems,
  roomStyles: s.roomStyles,
})

export interface AppState {
  // project / floorplan
  projectId: number | null
  projectName: string
  floorplanUrl: string | null
  floorplanSize: { w: number; h: number } | null
  floorplanOpacity: number
  floorplanLocked: boolean
  floorplanVisible: boolean
  pixelsPerCm: number | null
  /** true when pixelsPerCm was guessed automatically (not calibrated by the user) */
  scaleEstimated: boolean

  // scene (single source of truth for 2D + 3D; centimeters)
  ceilingHeightCm: number
  walls: Wall[]
  openings: Opening[]
  placedItems: PlacedItem[]
  roomStyles: RoomStyle[]

  // ui
  selected: Selection
  tool: Tool
  viewMode: ViewMode
  openingKind: OpeningKind
  newWallThicknessCm: number
  orthoSnap: boolean
  gridSnap: boolean
  showFloors: boolean
  toasts: Toast[]

  // catalog
  products: Product[]
  productsLoading: boolean
  catalogFilters: CatalogFilters
  modelStates: Record<number, ModelState>

  // history
  past: SceneState[]
  future: SceneState[]
  lastHistoryKey: string | null
  lastHistoryAt: number

  // actions
  setProjectName: (name: string) => void
  setProjectId: (id: number | null) => void
  setFloorplan: (url: string | null, size?: { w: number; h: number } | null) => void
  setFloorplanSize: (size: { w: number; h: number } | null) => void
  setFloorplanOpacity: (v: number) => void
  setFloorplanLocked: (v: boolean) => void
  setFloorplanVisible: (v: boolean) => void
  setPixelsPerCm: (v: number | null) => void
  setEstimatedScale: (v: number) => void

  setTool: (t: Tool) => void
  setViewMode: (v: ViewMode) => void
  setSelected: (s: Selection) => void
  setOpeningKind: (k: OpeningKind) => void
  setNewWallThickness: (v: number) => void
  setOrthoSnap: (v: boolean) => void
  setGridSnap: (v: boolean) => void
  setShowFloors: (v: boolean) => void
  /** Replace the style at `index` (or append when null). */
  upsertRoomStyle: (index: number | null, style: RoomStyle, key?: string) => void
  /** Give every room the same floor (clears per-room names' positions only for rooms listed). */
  setAllRoomMaterials: (points: { x: number; y: number; name?: string }[], material: RoomStyle['material']) => void

  /** Push one undo entry. Pass a key to coalesce rapid edits (sliders, number inputs). */
  pushHistory: (key?: string) => void
  undo: () => void
  redo: () => void

  setCeilingHeight: (cm: number) => void
  addWalls: (walls: Omit<Wall, 'id'>[]) => string[]
  updateWall: (id: string, patch: Partial<Omit<Wall, 'id'>>, key?: string) => void
  removeWall: (id: string) => void
  /** Add auto-detected walls (+ their openings) as ONE undo step. `replace` clears existing walls/openings first. */
  applyDetectedWalls: (walls: DetectedWall[], replace: boolean) => void
  addOpening: (o: Omit<Opening, 'id'>) => string
  updateOpening: (id: string, patch: Partial<Omit<Opening, 'id'>>, key?: string) => void
  removeOpening: (id: string) => void

  addItemFromProduct: (p: Product, xCm: number, zCm: number) => string
  /** Live move during a drag gesture (no history entry — call pushHistory() at drag start). */
  moveItemLive: (id: string, xCm: number, zCm: number) => void
  setItemRotationLive: (id: string, deg: number) => void
  updateItem: (id: string, patch: Partial<Pick<PlacedItem, 'xCm' | 'zCm' | 'rotationDeg'>>, key?: string) => void
  rotateItem90: (id: string) => void
  duplicateItem: (id: string) => string | null
  removeItem: (id: string) => void
  deleteSelected: () => void

  loadScene: (scene: SceneState) => void
  resetProject: () => void
  loadProject: (p: {
    id: number
    name: string
    floorplan_image_url: string | null
    pixels_per_cm: number | null
    scene: SceneState
  }) => void

  setProducts: (p: Product[]) => void
  setProductsLoading: (v: boolean) => void
  setCatalogFilters: (f: Partial<CatalogFilters>) => void
  upsertProductLocal: (p: Product) => void
  setModelState: (productId: number, s: ModelState) => void

  toast: (message: string, kind?: Toast['kind']) => void
  dismissToast: (id: string) => void
}

export const useAppStore = create<AppState>((set, get) => ({
  projectId: null,
  projectName: 'פרויקט חדש',
  floorplanUrl: null,
  floorplanSize: null,
  floorplanOpacity: 0.6,
  floorplanLocked: false,
  floorplanVisible: true,
  pixelsPerCm: null,
  scaleEstimated: false,

  ...emptyScene(),

  selected: null,
  tool: 'select',
  viewMode: 'split',
  openingKind: 'door',
  newWallThicknessCm: DEFAULT_WALL_THICKNESS_CM,
  orthoSnap: true,
  gridSnap: true,
  showFloors: true,
  toasts: [],

  products: [],
  productsLoading: false,
  catalogFilters: { search: '', category: '', maxWidthCm: '', maxPriceIls: '', sortBy: 'featured' },
  modelStates: {},

  past: [],
  future: [],
  lastHistoryKey: null,
  lastHistoryAt: 0,

  setProjectName: (name) => set({ projectName: name }),
  setProjectId: (id) => set({ projectId: id }),
  setFloorplan: (url, size = null) => set({ floorplanUrl: url, floorplanSize: size, floorplanVisible: true }),
  setFloorplanSize: (size) => set({ floorplanSize: size }),
  setFloorplanOpacity: (v) => set({ floorplanOpacity: v }),
  setFloorplanLocked: (v) => set({ floorplanLocked: v }),
  setFloorplanVisible: (v) => set({ floorplanVisible: v }),
  setPixelsPerCm: (v) => set({ pixelsPerCm: v, scaleEstimated: false }),
  setEstimatedScale: (v) => set({ pixelsPerCm: v, scaleEstimated: true }),

  setTool: (t) => set({ tool: t, ...(t !== 'select' ? { selected: null } : {}) }),
  setViewMode: (v) => set({ viewMode: v }),
  setSelected: (s) => set({ selected: s }),
  setOpeningKind: (k) => set({ openingKind: k }),
  setNewWallThickness: (v) => set({ newWallThicknessCm: v }),
  setOrthoSnap: (v) => set({ orthoSnap: v }),
  setGridSnap: (v) => set({ gridSnap: v }),
  setShowFloors: (v) => set({ showFloors: v }),
  upsertRoomStyle: (index, style, key) => {
    get().pushHistory(key ?? 'roomstyle')
    set((s) => ({
      roomStyles:
        index === null || index < 0 || index >= s.roomStyles.length
          ? [...s.roomStyles, style]
          : s.roomStyles.map((r, i) => (i === index ? style : r)),
    }))
  },
  setAllRoomMaterials: (points, material) => {
    get().pushHistory()
    set((s) => ({
      roomStyles: points.map((p) => {
        const old = s.roomStyles.find((r) => Math.hypot(r.x - p.x, r.y - p.y) < 1)
        return { x: p.x, y: p.y, material, name: p.name ?? old?.name }
      }),
    }))
  },

  pushHistory: (key) => {
    const s = get()
    const now = Date.now()
    if (key && s.lastHistoryKey === key && now - s.lastHistoryAt < 900) {
      set({ lastHistoryAt: now })
      return
    }
    const past = [...s.past, sceneOf(s)].slice(-HISTORY_LIMIT)
    set({ past, future: [], lastHistoryKey: key ?? null, lastHistoryAt: now })
  },
  undo: () => {
    const s = get()
    const prev = s.past[s.past.length - 1]
    if (!prev) return
    set({
      ...prev,
      past: s.past.slice(0, -1),
      future: [sceneOf(s), ...s.future].slice(0, HISTORY_LIMIT),
      lastHistoryKey: null,
      selected: null,
    })
  },
  redo: () => {
    const s = get()
    const next = s.future[0]
    if (!next) return
    set({
      ...next,
      past: [...s.past, sceneOf(s)].slice(-HISTORY_LIMIT),
      future: s.future.slice(1),
      lastHistoryKey: null,
      selected: null,
    })
  },

  setCeilingHeight: (cm) => {
    get().pushHistory('ceiling')
    set({ ceilingHeightCm: Math.max(150, Math.min(600, cm || DEFAULT_CEILING_CM)) })
  },

  addWalls: (walls) => {
    get().pushHistory()
    const created = walls.map((w) => ({ ...w, id: uid('wall') }))
    set((s) => ({ walls: [...s.walls, ...created] }))
    return created.map((w) => w.id)
  },
  updateWall: (id, patch, key) => {
    get().pushHistory(key ?? `wall:${id}`)
    set((s) => ({
      walls: s.walls.map((w) => (w.id === id ? { ...w, ...patch } : w)),
      // keep openings inside the (possibly shortened) wall
      openings: s.openings.map((o) => {
        if (o.wallId !== id) return o
        const w = s.walls.find((x) => x.id === id)
        if (!w) return o
        const merged = { ...w, ...patch }
        const len = wallLength(merged)
        return { ...o, offsetCm: Math.max(0, Math.min(len, o.offsetCm)) }
      }),
    }))
  },
  removeWall: (id) => {
    get().pushHistory()
    set((s) => ({
      walls: s.walls.filter((w) => w.id !== id),
      openings: s.openings.filter((o) => o.wallId !== id),
      selected: s.selected?.id === id ? null : s.selected,
    }))
  },
  applyDetectedWalls: (detected, replace) => {
    get().pushHistory()
    const newWalls: Wall[] = []
    const newOpenings: Opening[] = []
    for (const d of detected) {
      const wall: Wall = { id: uid('wall'), x1: d.x1, y1: d.y1, x2: d.x2, y2: d.y2, thicknessCm: d.thicknessCm }
      newWalls.push(wall)
      for (const o of d.openings) newOpenings.push({ id: uid('open'), wallId: wall.id, ...o })
    }
    set((s) => ({
      walls: replace ? newWalls : [...s.walls, ...newWalls],
      openings: replace ? newOpenings : [...s.openings, ...newOpenings],
      roomStyles: replace ? [] : s.roomStyles,
      selected: null,
    }))
  },
  addOpening: (o) => {
    get().pushHistory()
    const id = uid('open')
    set((s) => ({ openings: [...s.openings, { ...o, id }] }))
    return id
  },
  updateOpening: (id, patch, key) => {
    get().pushHistory(key ?? `open:${id}`)
    set((s) => ({ openings: s.openings.map((o) => (o.id === id ? { ...o, ...patch } : o)) }))
  },
  removeOpening: (id) => {
    get().pushHistory()
    set((s) => ({
      openings: s.openings.filter((o) => o.id !== id),
      selected: s.selected?.id === id ? null : s.selected,
    }))
  },

  addItemFromProduct: (p, xCm, zCm) => {
    get().pushHistory()
    const id = uid('item')
    const item: PlacedItem = {
      id,
      productId: p.id,
      xCm,
      zCm,
      rotationDeg: 0,
      title: p.title,
      storeName: p.store_name,
      productUrl: p.product_url,
      priceIls: p.price_ils,
      category: p.category,
      widthCm: p.width_cm,
      depthCm: p.depth_cm,
      heightCm: p.height_cm,
      imageUrl: p.image_url,
    }
    set((s) => ({ placedItems: [...s.placedItems, item], selected: { type: 'item', id }, tool: 'select' }))
    return id
  },
  moveItemLive: (id, xCm, zCm) =>
    set((s) => ({ placedItems: s.placedItems.map((i) => (i.id === id ? { ...i, xCm, zCm } : i)) })),
  setItemRotationLive: (id, deg) =>
    set((s) => ({
      placedItems: s.placedItems.map((i) => (i.id === id ? { ...i, rotationDeg: ((deg % 360) + 360) % 360 } : i)),
    })),
  updateItem: (id, patch, key) => {
    get().pushHistory(key ?? `item:${id}`)
    set((s) => ({
      placedItems: s.placedItems.map((i) =>
        i.id === id
          ? {
              ...i,
              ...patch,
              ...(patch.rotationDeg !== undefined ? { rotationDeg: ((patch.rotationDeg % 360) + 360) % 360 } : {}),
            }
          : i,
      ),
    }))
  },
  rotateItem90: (id) => {
    get().pushHistory()
    set((s) => ({
      placedItems: s.placedItems.map((i) => (i.id === id ? { ...i, rotationDeg: (i.rotationDeg + 90) % 360 } : i)),
    }))
  },
  duplicateItem: (id) => {
    const src = get().placedItems.find((i) => i.id === id)
    if (!src) return null
    get().pushHistory()
    const nid = uid('item')
    const copy: PlacedItem = { ...src, id: nid, xCm: src.xCm + 30, zCm: src.zCm + 30 }
    set((s) => ({ placedItems: [...s.placedItems, copy], selected: { type: 'item', id: nid } }))
    return nid
  },
  removeItem: (id) => {
    get().pushHistory()
    set((s) => ({
      placedItems: s.placedItems.filter((i) => i.id !== id),
      selected: s.selected?.id === id ? null : s.selected,
    }))
  },
  deleteSelected: () => {
    const sel = get().selected
    if (!sel) return
    if (sel.type === 'item') get().removeItem(sel.id)
    else if (sel.type === 'wall') get().removeWall(sel.id)
    else get().removeOpening(sel.id)
  },

  loadScene: (scene) =>
    set({ ...scene, selected: null, past: [], future: [], lastHistoryKey: null }),
  resetProject: () =>
    set({
      projectId: null,
      projectName: 'פרויקט חדש',
      floorplanUrl: null,
      floorplanSize: null,
      pixelsPerCm: null,
      scaleEstimated: false,
      ...emptyScene(),
      selected: null,
      tool: 'select',
      past: [],
      future: [],
      lastHistoryKey: null,
      modelStates: get().modelStates,
    }),
  loadProject: (p) =>
    set({
      projectId: p.id,
      projectName: p.name,
      floorplanUrl: p.floorplan_image_url,
      floorplanSize: null,
      pixelsPerCm: p.pixels_per_cm,
      scaleEstimated: false,
      ceilingHeightCm: p.scene.ceilingHeightCm ?? DEFAULT_CEILING_CM,
      walls: p.scene.walls ?? [],
      openings: p.scene.openings ?? [],
      placedItems: p.scene.placedItems ?? [],
      roomStyles: p.scene.roomStyles ?? [],
      selected: null,
      tool: 'select',
      past: [],
      future: [],
      lastHistoryKey: null,
    }),

  setProducts: (products) => set({ products }),
  setProductsLoading: (v) => set({ productsLoading: v }),
  setCatalogFilters: (f) => set((s) => ({ catalogFilters: { ...s.catalogFilters, ...f } })),
  upsertProductLocal: (p) =>
    set((s) => ({
      products: s.products.some((x) => x.id === p.id)
        ? s.products.map((x) => (x.id === p.id ? p : x))
        : [p, ...s.products],
    })),
  setModelState: (productId, st) => set((s) => ({ modelStates: { ...s.modelStates, [productId]: st } })),

  toast: (message, kind = 'info') => {
    const id = uid('toast')
    set((s) => ({ toasts: [...s.toasts, { id, message, kind }] }))
    setTimeout(() => get().dismissToast(id), kind === 'error' ? 6000 : 3500)
  },
  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))

export const selectScene = (s: AppState): SceneState => sceneOf(s)
export const selectBudgetTotal = (s: AppState): number => s.placedItems.reduce((sum, i) => sum + i.priceIls, 0)
