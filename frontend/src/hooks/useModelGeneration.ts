import { useEffect } from 'react'
import { api } from '../api/client'
import { useAppStore } from '../store/useAppStore'
import type { ModelStatusInfo, Product } from '../types'

const POLL_MS = 1500
const MAX_POLLS = 400 // ~10 minutes
const inflight = new Set<number>()

function applyStatus(productId: number, info: ModelStatusInfo | Product) {
  const st = useAppStore.getState()
  st.setModelState(productId, {
    status: info.model_status,
    url: info.model_3d_url,
    error: info.model_error,
  })
  // keep the catalog card badge in sync
  const existing = st.products.find((p) => p.id === productId)
  if (existing) {
    st.upsertProductLocal({
      ...existing,
      model_status: info.model_status,
      model_3d_url: info.model_3d_url,
      model_error: info.model_error,
    })
  }
}

async function poll(productId: number) {
  for (let i = 0; i < MAX_POLLS; i++) {
    await new Promise((r) => setTimeout(r, POLL_MS))
    try {
      const info = await api.status3d(productId)
      if (info.model_status === 'none') {
        // the server lost the job (restart / orphaned task): start it again
        applyStatus(productId, await api.generate3d(productId))
        continue
      }
      applyStatus(productId, info)
      if (info.model_status === 'ready' || info.model_status === 'failed') return
    } catch {
      /* transient network error — keep polling */
    }
  }
  useAppStore.getState().setModelState(productId, { status: 'failed', url: null, error: 'timeout' })
}

/**
 * Lazy generation flow for one product:
 *  - cached (`ready`) → reuse immediately with zero API calls
 *  - `none` / `failed` → POST generate-3d, then poll 3d-status until ready
 *  - `generating` → just poll
 */
export async function ensureModel(productId: number, opts: { retryFailed?: boolean } = {}): Promise<void> {
  const store = useAppStore.getState()
  const known = store.modelStates[productId]
  if (inflight.has(productId)) return
  if (known?.status === 'ready' || known?.status === 'generating') return
  if (known?.status === 'failed' && !opts.retryFailed) return

  inflight.add(productId)
  try {
    const product = await api.getProduct(productId)
    if (product.model_status === 'ready' && product.model_3d_url) {
      applyStatus(productId, product)
      return
    }
    if (product.model_status === 'generating') {
      applyStatus(productId, product)
    } else {
      // optimistic: show "generating" immediately so the placeholder pill appears
      store.setModelState(productId, { status: 'generating', url: null, error: null })
      const info = await api.generate3d(productId)
      applyStatus(productId, info)
      if (info.model_status === 'ready') return
      if (info.model_status === 'failed') return
    }
    await poll(productId)
  } catch (e) {
    useAppStore.getState().setModelState(productId, {
      status: 'failed',
      url: null,
      error: e instanceof Error ? e.message : 'error',
    })
  } finally {
    inflight.delete(productId)
  }
}

/** Throw away the cached model of one product and generate it again (e.g. after a better provider was configured). */
export async function regenerateModel(productId: number): Promise<void> {
  useAppStore.getState().setModelState(productId, { status: 'generating', url: null, error: null })
  try {
    const info = await api.generate3d(productId, true)
    applyStatus(productId, info)
    if (info.model_status === 'generating') await poll(productId)
  } catch (e) {
    useAppStore.getState().setModelState(productId, {
      status: 'failed',
      url: null,
      error: e instanceof Error ? e.message : 'error',
    })
  }
}

/** Mount once: makes sure every product used in the scene has (or is getting) a 3D model. */
export function useModelOrchestrator() {
  const items = useAppStore((s) => s.placedItems)
  const modelStates = useAppStore((s) => s.modelStates)
  useEffect(() => {
    const ids = new Set(items.filter((i) => !i.fixture).map((i) => i.productId))
    ids.forEach((id) => {
      if (!modelStates[id]) void ensureModel(id)
    })
  }, [items, modelStates])
}

/** Place a catalog product at (x, z) cm and kick off lazy generation if needed. */
export function placeProduct(product: Product, xCm: number, zCm: number): string {
  const id = useAppStore.getState().addItemFromProduct(product, xCm, zCm)
  void ensureModel(product.id, { retryFailed: true })
  return id
}
