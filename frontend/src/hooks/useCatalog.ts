import { useCallback, useEffect, useRef } from 'react'
import { create } from 'zustand'
import { api, type ProductFilters } from '../api/client'
import { useAppStore } from '../store/useAppStore'

/** Cards rendered per "page" of the catalog list (the backend can hold thousands of products). */
export const CATALOG_PAGE_SIZE = 60

/** Tiny UI-only store for the "show more" paging of the catalog list (scene/catalog data stays in the main store). */
export const useCatalogPaging = create<{
  limit: number
  hasMore: boolean
  showMore: () => void
  reset: () => void
  setHasMore: (v: boolean) => void
}>((set) => ({
  limit: CATALOG_PAGE_SIZE,
  hasMore: false,
  showMore: () => set((s) => ({ limit: s.limit + CATALOG_PAGE_SIZE })),
  reset: () => set({ limit: CATALOG_PAGE_SIZE }),
  setHasMore: (hasMore) => set({ hasMore }),
}))

/** Loads the catalog from the backend whenever filters / page size change (debounced for text/number inputs). */
export function useCatalogLoader() {
  const filters = useAppStore((s) => s.catalogFilters)
  const limit = useCatalogPaging((s) => s.limit)
  const setProducts = useAppStore((s) => s.setProducts)
  const setLoading = useAppStore((s) => s.setProductsLoading)
  const toast = useAppStore((s) => s.toast)
  const reqId = useRef(0)

  const load = useCallback(async () => {
    const id = ++reqId.current
    setLoading(true)
    try {
      const f = useAppStore.getState().catalogFilters
      const pageLimit = useCatalogPaging.getState().limit
      // ask for one extra row to know whether there is more to show
      const query: ProductFilters & { limit: number } = {
        search: f.search.trim() || undefined,
        category: f.category || undefined,
        max_width_cm: f.maxWidthCm ? Number(f.maxWidthCm) : undefined,
        max_price_ils: f.maxPriceIls ? Number(f.maxPriceIls) : undefined,
        sort_by: f.sortBy,
        limit: pageLimit + 1,
      }
      const fetched = await api.listProducts(query)
      if (id !== reqId.current) return
      useCatalogPaging.getState().setHasMore(fetched.length > pageLimit)
      const list = fetched.slice(0, pageLimit)
      // merge live model state (generation may be in progress locally)
      const ms = useAppStore.getState().modelStates
      setProducts(
        list.map((p) =>
          ms[p.id] ? { ...p, model_status: ms[p.id].status, model_3d_url: ms[p.id].url ?? p.model_3d_url } : p,
        ),
      )
    } catch (e) {
      if (id === reqId.current) toast(e instanceof Error ? e.message : 'שגיאה בטעינת הקטלוג', 'error')
    } finally {
      if (id === reqId.current) setLoading(false)
    }
  }, [setProducts, setLoading, toast])

  // a changed filter starts again from the first page
  useEffect(() => {
    useCatalogPaging.getState().reset()
  }, [filters])

  useEffect(() => {
    const t = setTimeout(load, 250)
    return () => clearTimeout(t)
  }, [filters, limit, load])

  return load
}
