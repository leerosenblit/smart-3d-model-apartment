import type { Point, Product } from '../types'
import { sceneBounds } from './geometry'
import { useAppStore } from '../store/useAppStore'
import { placeProduct } from '../hooks/useModelGeneration'

/** Lets non-view components (sidebar "add" button) ask where the user is currently looking. */
export const viewRegistry: { center2d: (() => Point) | null } = { center2d: null }

export function getPlacementCenter(): Point {
  if (viewRegistry.center2d) return viewRegistry.center2d()
  const b = sceneBounds(useAppStore.getState())
  return { x: (b.minX + b.maxX) / 2, y: (b.minY + b.maxY) / 2 }
}

/** Add a product at the center of the active view (with a small stagger so repeats don't stack exactly). */
export function addProductAtCenter(product: Product): void {
  const c = getPlacementCenter()
  const n = useAppStore.getState().placedItems.length % 6
  placeProduct(product, Math.round(c.x + n * 20), Math.round(c.y + n * 20))
}
