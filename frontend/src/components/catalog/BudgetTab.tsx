import { useMemo } from 'react'
import { useAppStore } from '../../store/useAppStore'
import { CATEGORY_LABELS } from '../../utils/labels'
import { buildBom, bomToCsv, downloadCsv } from '../../utils/csv'
import { formatDims, formatIls } from '../../utils/format'
import { ProductThumb } from './ProductCard'

export function BudgetTab() {
  const items = useAppStore((s) => s.placedItems)
  const name = useAppStore((s) => s.projectName)
  const setSelected = useAppStore((s) => s.setSelected)

  const lines = useMemo(() => buildBom(items), [items])
  const total = lines.reduce((s, l) => s + l.subtotal, 0)
  const count = lines.reduce((s, l) => s + l.qty, 0)

  const exportCsv = () => {
    const safe = (name || 'roomcraft').replace(/[\\/:*?"<>|]+/g, '_')
    downloadCsv(`${safe}-shopping-list.csv`, bomToCsv(lines))
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        {lines.length === 0 && (
          <p className="py-10 text-center text-sm text-slate-400">
            עדיין לא הוספתם פריטים לדירה.
            <br />
            גררו מוצרים מהקטלוג אל התוכנית.
          </p>
        )}
        {lines.map((l) => (
          <div key={l.productId} className="rounded-lg border border-slate-200 bg-white p-2.5 shadow-sm" data-testid="bom-line">
            <div className="flex items-start gap-2">
              <ProductThumb
                productId={l.productId}
                imageUrl={items.find((i) => i.productId === l.productId)?.imageUrl ?? ''}
                className="h-12 w-14"
              />
              <div className="flex min-w-0 flex-1 items-start justify-between gap-2">
                <button
                  className="min-w-0 text-start text-sm font-semibold text-slate-800 hover:text-brand-600"
                  onClick={() => {
                    const it = items.find((i) => i.productId === l.productId)
                    if (it) setSelected({ type: 'item', id: it.id })
                  }}
                  title="בחר פריט בתוכנית"
                >
                  <span className="line-clamp-2">{l.title}</span>
                </button>
                <span className="shrink-0 rounded-full bg-brand-50 px-2 py-0.5 text-xs font-bold text-brand-700">×{l.qty}</span>
              </div>
            </div>
            <div className="mt-0.5 text-[11px] text-slate-500">
              {l.storeName} · {CATEGORY_LABELS[l.category as keyof typeof CATEGORY_LABELS] ?? l.category}
            </div>
            <div className="ltr text-start text-[11px] text-slate-500">{formatDims(l.widthCm, l.depthCm, l.heightCm)}</div>
            <div className="mt-1 flex items-center justify-between text-sm">
              <span className="text-slate-500">
                {formatIls(l.unitPrice)} × {l.qty}
              </span>
              <span className="font-bold text-slate-800">{formatIls(l.subtotal)}</span>
            </div>
            {l.productUrl && /^https?:/.test(l.productUrl) && (
              <a href={l.productUrl} target="_blank" rel="noreferrer" className="mt-1 inline-block text-xs text-brand-600 underline">
                לדף המוצר בחנות ↗
              </a>
            )}
          </div>
        ))}
      </div>
      <div className="border-t border-slate-200 bg-white p-3">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm text-slate-500">{count} פריטים</span>
          <span className="text-xl font-extrabold text-brand-700" data-testid="budget-total">
            {formatIls(total)}
          </span>
        </div>
        <button className="btn w-full" disabled={!lines.length} onClick={exportCsv}>
          ⬇ ייצוא CSV
        </button>
      </div>
    </div>
  )
}
