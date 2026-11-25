import { api } from '../api/client'
import { useAppStore } from '../store/useAppStore'
import type { Product } from '../types'
import { DND_MIME } from './labels'

export const isProductDrag = (e: { dataTransfer: DataTransfer | null }): boolean =>
  !!e.dataTransfer && Array.from(e.dataTransfer.types).includes(DND_MIME)

/** Resolve a product dragged from the catalog sidebar (store first, API as fallback). */
export async function resolveDroppedProduct(dt: DataTransfer): Promise<Product | null> {
  const raw = dt.getData(DND_MIME)
  const id = Number(raw)
  if (!raw || !Number.isFinite(id)) return null
  const local = useAppStore.getState().products.find((p) => p.id === id)
  if (local) return local
  try {
    return await api.getProduct(id)
  } catch {
    return null
  }
}
