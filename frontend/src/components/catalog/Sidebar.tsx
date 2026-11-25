import { useState } from 'react'
import { useCatalogLoader } from '../../hooks/useCatalog'
import { useAppStore } from '../../store/useAppStore'
import { BudgetTab } from './BudgetTab'
import { CatalogTab } from './CatalogTab'
import { ImportTab } from './ImportTab'

type Tab = 'catalog' | 'import' | 'budget'

export function Sidebar() {
  const [tab, setTab] = useState<Tab>('catalog')
  const reload = useCatalogLoader()
  const itemCount = useAppStore((s) => s.placedItems.filter((i) => !i.fixture).length)

  const tabs: { id: Tab; label: string }[] = [
    { id: 'catalog', label: 'קטלוג מוצרים' },
    { id: 'import', label: 'ייבוא מהאינטרנט' },
    { id: 'budget', label: `תקציב ורשימת קניות${itemCount ? ` (${itemCount})` : ''}` },
  ]

  return (
    <aside className="flex h-full w-[360px] shrink-0 flex-col border-s border-slate-200 bg-slate-50" data-testid="sidebar">
      <div className="flex border-b border-slate-200 bg-white">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex-1 px-1 py-2.5 text-xs font-semibold transition ${
              tab === t.id ? 'border-b-2 border-brand-600 text-brand-700' : 'text-slate-500 hover:bg-slate-50'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1">
        {tab === 'catalog' && <CatalogTab />}
        {tab === 'import' && <ImportTab onChanged={reload} />}
        {tab === 'budget' && <BudgetTab />}
      </div>
    </aside>
  )
}
