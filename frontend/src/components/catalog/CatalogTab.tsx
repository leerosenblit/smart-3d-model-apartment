import { useAppStore } from '../../store/useAppStore'
import { CATEGORY_LABELS, CATEGORY_ORDER } from '../../utils/labels'
import { useCatalogPaging } from '../../hooks/useCatalog'
import { ProductCard } from './ProductCard'

export function CatalogTab() {
  const products = useAppStore((s) => s.products)
  const loading = useAppStore((s) => s.productsLoading)
  const filters = useAppStore((s) => s.catalogFilters)
  const setFilters = useAppStore((s) => s.setCatalogFilters)
  const hasMore = useCatalogPaging((s) => s.hasMore)
  const showMore = useCatalogPaging((s) => s.showMore)

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="space-y-2 border-b border-slate-200 p-3">
        <input
          className="field"
          placeholder="חיפוש מוצר או חנות…"
          value={filters.search}
          onChange={(e) => setFilters({ search: e.target.value })}
          data-testid="catalog-search"
        />
        <div className="flex flex-wrap gap-1">
          <button
            className={`chip ${filters.category === '' ? 'chip-active' : ''}`}
            onClick={() => setFilters({ category: '' })}
          >
            הכל
          </button>
          {CATEGORY_ORDER.map((c) => (
            <button
              key={c}
              className={`chip ${filters.category === c ? 'chip-active' : ''}`}
              onClick={() => setFilters({ category: filters.category === c ? '' : c })}
            >
              {CATEGORY_LABELS[c]}
            </button>
          ))}
        </div>
        <div className="grid grid-cols-3 gap-2">
          <div>
            <label className="label">רוחב מקס׳ (ס"מ)</label>
            <input
              className="field ltr"
              type="number"
              min={0}
              inputMode="numeric"
              value={filters.maxWidthCm}
              onChange={(e) => setFilters({ maxWidthCm: e.target.value })}
            />
          </div>
          <div>
            <label className="label">מחיר מקס׳ (₪)</label>
            <input
              className="field ltr"
              type="number"
              min={0}
              inputMode="numeric"
              value={filters.maxPriceIls}
              onChange={(e) => setFilters({ maxPriceIls: e.target.value })}
            />
          </div>
          <div>
            <label className="label">מיון</label>
            <select className="field" value={filters.sortBy} onChange={(e) => setFilters({ sortBy: e.target.value })}>
              <option value="featured">מומלצים</option>
              <option value="updated">חדשים</option>
              <option value="price_asc">מחיר ↑</option>
              <option value="price_desc">מחיר ↓</option>
              <option value="width">רוחב</option>
              <option value="title">שם</option>
            </select>
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        {loading && products.length === 0 && <p className="text-center text-sm text-slate-400">טוען…</p>}
        {!loading && products.length === 0 && (
          <p className="py-8 text-center text-sm text-slate-400">לא נמצאו מוצרים התואמים לסינון</p>
        )}
        {products.map((p) => (
          <ProductCard key={p.id} product={p} />
        ))}
        {hasMore && (
          <button className="btn w-full" onClick={showMore} disabled={loading} data-testid="catalog-show-more">
            {loading ? 'טוען…' : 'הצג עוד'}
          </button>
        )}
      </div>
    </div>
  )
}
