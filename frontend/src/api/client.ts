import type {
  DetectedWall,
  FloorplanUploadResult,
  IngestResult,
  ModelStatusInfo,
  Product,
  ProductInput,
  ProjectRead,
  ProjectSummary,
  RoomHint,
  SceneState,
} from '../types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, init)
  } catch {
    throw new ApiError(0, 'אין חיבור לשרת')
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail || `שגיאה ${res.status}`)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export interface ProductFilters {
  search?: string
  category?: string
  store_name?: string
  max_width_cm?: number
  max_depth_cm?: number
  max_price_ils?: number
  sort_by?: string
  limit?: number
}

export const api = {
  // products
  listProducts(filters: ProductFilters = {}): Promise<Product[]> {
    const q = new URLSearchParams()
    for (const [k, v] of Object.entries(filters)) {
      if (v !== undefined && v !== '' && v !== null) q.set(k, String(v))
    }
    return request(`/api/products?${q.toString()}`)
  },
  getProduct: (id: number): Promise<Product> => request(`/api/products/${id}`),
  createProduct: (p: ProductInput): Promise<Product> => request('/api/products', json('POST', p)),
  deleteProduct: (id: number): Promise<void> => request(`/api/products/${id}`, { method: 'DELETE' }),
  listStores: (): Promise<string[]> => request('/api/products/stores'),
  ingestBatch: (urls: string[]): Promise<IngestResult[]> =>
    request('/api/products/ingest-batch', json('POST', { urls })),

  // lazy 3D
  generate3d: (id: number): Promise<ModelStatusInfo> =>
    request(`/api/products/${id}/generate-3d`, { method: 'POST' }),
  status3d: (id: number): Promise<ModelStatusInfo> => request(`/api/products/${id}/3d-status`),

  // projects
  listProjects: (): Promise<ProjectSummary[]> => request('/api/projects'),
  getProject: (id: number): Promise<ProjectRead> => request(`/api/projects/${id}`),
  createProject(body: {
    name: string
    floorplan_image_url: string | null
    pixels_per_cm: number | null
    scene: SceneState
  }): Promise<ProjectRead> {
    return request('/api/projects', json('POST', body))
  },
  updateProject(
    id: number,
    body: { name: string; floorplan_image_url: string | null; pixels_per_cm: number | null; scene: SceneState },
  ): Promise<ProjectRead> {
    return request(`/api/projects/${id}`, json('PUT', body))
  },
  deleteProject: (id: number): Promise<void> => request(`/api/projects/${id}`, { method: 'DELETE' }),

  // floorplans
  uploadFloorplan(file: File): Promise<FloorplanUploadResult> {
    const fd = new FormData()
    fd.append('file', file)
    return request('/api/floorplans/upload', { method: 'POST', body: fd })
  },
  detectWalls: (
    url: string,
    pixelsPerCm: number | null,
  ): Promise<{ walls: DetectedWall[]; room_hints: RoomHint[]; pixels_per_cm: number | null; scale_estimated: boolean }> =>
    request('/api/floorplans/detect-walls', json('POST', { url, pixels_per_cm: pixelsPerCm })),
}
