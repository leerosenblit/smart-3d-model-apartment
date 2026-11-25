// Shared types mirroring backend schemas. ALL lengths are centimeters.

export type Category =
  | 'sofa'
  | 'armchair'
  | 'tv_unit'
  | 'coffee_table'
  | 'dining_table'
  | 'chair'
  | 'bed'
  | 'wardrobe'
  | 'storage'
  | 'desk'
  | 'appliance'
  | 'lighting'
  | 'decor'
  | 'other'

export type ModelStatus = 'none' | 'generating' | 'ready' | 'failed'

export interface Product {
  id: number
  store_name: string
  product_url: string
  title: string
  category: Category
  price_ils: number
  width_cm: number
  depth_cm: number
  height_cm: number
  image_url: string
  model_3d_url: string | null
  model_status: ModelStatus
  model_error: string | null
  updated_at: string
}

export type ProductInput = Pick<
  Product,
  'store_name' | 'product_url' | 'title' | 'category' | 'price_ils' | 'width_cm' | 'depth_cm' | 'height_cm' | 'image_url'
>

export interface ModelStatusInfo {
  id: number
  model_status: ModelStatus
  model_3d_url: string | null
  model_error: string | null
}

export interface IngestResult {
  url: string
  status: 'created' | 'updated' | 'failed'
  source: string | null
  product: Product | null
  error: string | null
}

// ---- Scene (plan coordinates: x → right, y → down; plan-y maps to 3D world-z)

export interface Wall {
  id: string
  x1: number
  y1: number
  x2: number
  y2: number
  thicknessCm: number
}

export type OpeningKind = 'door' | 'window'

export interface Opening {
  id: string
  wallId: string
  kind: OpeningKind
  /** distance from the wall start (x1,y1) to the opening CENTER, along the wall */
  offsetCm: number
  widthCm: number
  heightCm: number
  sillCm: number
}

export interface PlacedItem {
  id: string
  productId: number
  xCm: number
  /** plan-y (maps to world z) */
  zCm: number
  /** clockwise on the 2D plan, degrees */
  rotationDeg: number
  title: string
  storeName: string
  productUrl: string
  priceIls: number
  category: Category
  widthCm: number
  depthCm: number
  heightCm: number
  imageUrl: string
}

export type FloorMaterialId = 'oak' | 'walnut' | 'tile_white' | 'tile_beige' | 'concrete' | 'carpet'

/** User choice for the room that contains plan point (x, y). Rooms themselves are derived from the walls. */
export interface RoomStyle {
  x: number
  y: number
  material: FloorMaterialId
  name?: string
}

export interface SceneState {
  ceilingHeightCm: number
  walls: Wall[]
  openings: Opening[]
  placedItems: PlacedItem[]
  roomStyles: RoomStyle[]
}

export interface ProjectSummary {
  id: number
  name: string
  updated_at: string
}

export interface ProjectRead {
  id: number
  name: string
  floorplan_image_url: string | null
  pixels_per_cm: number | null
  scene: SceneState
  updated_at: string
}

export interface FloorplanUploadResult {
  url: string
  width_px: number
  height_px: number
}

export type Tool = 'select' | 'calibrate' | 'wall' | 'opening' | 'ruler'
export type ViewMode = '2d' | 'split' | '3d'
/** For type 'room' the id is `${x}:${y}` — a plan point inside the room */
export type Selection = { type: 'wall' | 'opening' | 'item' | 'room'; id: string } | null

export interface ModelState {
  status: ModelStatus
  url: string | null
  error: string | null
}

export interface Point {
  x: number
  y: number
}

export interface DetectedWall {
  x1: number
  y1: number
  x2: number
  y2: number
  thicknessCm: number
  openings: { kind: OpeningKind; offsetCm: number; widthCm: number; heightCm: number; sillCm: number }[]
}
