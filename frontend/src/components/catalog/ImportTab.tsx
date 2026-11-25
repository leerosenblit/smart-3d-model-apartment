import { useState } from 'react'
import { api } from '../../api/client'
import { useAppStore } from '../../store/useAppStore'
import type { Category, IngestResult } from '../../types'
import { CATEGORY_LABELS, CATEGORY_ORDER } from '../../utils/labels'
import { formatDims, formatIls } from '../../utils/format'

const SOURCE_LABELS: Record<string, string> = {
  jsonld: 'JSON-LD',
  microdata: 'Microdata',
  opengraph: 'OpenGraph',
  html: 'HTML',
  llm: 'AI',
}

const emptyForm = {
  title: '',
  store_name: '',
  product_url: '',
  category: 'other' as Category,
  price_ils: '',
  width_cm: '',
  depth_cm: '',
  height_cm: '',
  image_url: '',
}

export function ImportTab({ onChanged }: { onChanged: () => void }) {
  const toast = useAppStore((s) => s.toast)
  const [urls, setUrls] = useState('')
  const [busy, setBusy] = useState(false)
  const [results, setResults] = useState<IngestResult[]>([])
  const [form, setForm] = useState(emptyForm)
  const [saving, setSaving] = useState(false)

  const importUrls = async () => {
    const list = urls.split(/\r?\n/).map((u) => u.trim()).filter(Boolean)
    if (!list.length) return
    setBusy(true)
    try {
      const res = await api.ingestBatch(list)
      setResults(res)
      const ok = res.filter((r) => r.status !== 'failed').length
      toast(`יובאו ${ok} מתוך ${res.length} מוצרים`, ok ? 'success' : 'error')
      if (ok) onChanged()
    } catch (e) {
      toast(e instanceof Error ? e.message : 'שגיאת ייבוא', 'error')
    } finally {
      setBusy(false)
    }
  }

  const set = (k: keyof typeof emptyForm, v: string) => setForm((f) => ({ ...f, [k]: v }))
  const valid =
    form.title.trim() &&
    Number(form.width_cm) > 0 &&
    Number(form.depth_cm) > 0 &&
    Number(form.height_cm) > 0

  const saveManual = async () => {
    if (!valid) return
    setSaving(true)
    try {
      const url = form.product_url.trim() || `manual://${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
      const p = await api.createProduct({
        title: form.title.trim(),
        store_name: form.store_name.trim() || 'ידני',
        product_url: url,
        category: form.category,
        price_ils: Number(form.price_ils) || 0,
        width_cm: Number(form.width_cm),
        depth_cm: Number(form.depth_cm),
        height_cm: Number(form.height_cm),
        image_url: form.image_url.trim(),
      })
      toast(`"${p.title}" נוסף לקטלוג`, 'success')
      setForm(emptyForm)
      onChanged()
    } catch (e) {
      toast(e instanceof Error ? e.message : 'שגיאה בשמירה', 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="h-full space-y-5 overflow-y-auto p-3">
      <section>
        <h3 className="mb-1 text-sm font-bold text-slate-700">ייבוא מקישורי חנויות</h3>
        <p className="mb-2 text-xs text-slate-500">הדביקו קישור אחד או כמה (כל קישור בשורה נפרדת). המידות והמחיר יחולצו אוטומטית.</p>
        <textarea
          className="field ltr h-24 resize-y font-mono text-xs"
          placeholder={'https://store.co.il/product/1\nhttps://store.co.il/product/2'}
          value={urls}
          onChange={(e) => setUrls(e.target.value)}
          data-testid="import-urls"
        />
        <button className="btn btn-primary mt-2 w-full" disabled={busy || !urls.trim()} onClick={importUrls}>
          {busy ? 'מייבא…' : 'ייבא לקטלוג'}
        </button>

        {results.length > 0 && (
          <ul className="mt-3 space-y-1.5">
            {results.map((r) => (
              <li
                key={r.url}
                className={`rounded-md border p-2 text-xs ${
                  r.status === 'failed' ? 'border-red-200 bg-red-50' : 'border-emerald-200 bg-emerald-50'
                }`}
              >
                <div className="ltr truncate text-start text-[10px] text-slate-500">{r.url}</div>
                {r.status === 'failed' ? (
                  <div className="font-medium text-red-700">✗ {r.error}</div>
                ) : (
                  r.product && (
                    <div className="text-emerald-800">
                      <b>{r.status === 'created' ? '✓ נוסף' : '↻ עודכן'}:</b> {r.product.title} ·{' '}
                      {formatDims(r.product.width_cm, r.product.depth_cm, r.product.height_cm)} ·{' '}
                      {formatIls(r.product.price_ils)}
                      {r.source && <span className="ms-1 text-[10px] opacity-70">({SOURCE_LABELS[r.source] ?? r.source})</span>}
                    </div>
                  )
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="border-t border-slate-200 pt-4">
        <h3 className="mb-2 text-sm font-bold text-slate-700">הוספה ידנית</h3>
        <div className="space-y-2">
          <div>
            <label className="label">שם המוצר *</label>
            <input className="field" value={form.title} onChange={(e) => set('title', e.target.value)} data-testid="manual-title" />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="label">חנות</label>
              <input className="field" value={form.store_name} onChange={(e) => set('store_name', e.target.value)} />
            </div>
            <div>
              <label className="label">קטגוריה</label>
              <select className="field" value={form.category} onChange={(e) => set('category', e.target.value)}>
                {CATEGORY_ORDER.map((c) => (
                  <option key={c} value={c}>
                    {CATEGORY_LABELS[c]}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2">
            {(
              [
                ['width_cm', 'רוחב *'],
                ['depth_cm', 'עומק *'],
                ['height_cm', 'גובה *'],
              ] as const
            ).map(([k, label]) => (
              <div key={k}>
                <label className="label">{label} (ס"מ)</label>
                <input
                  className="field ltr"
                  type="number"
                  min={1}
                  value={form[k]}
                  onChange={(e) => set(k, e.target.value)}
                  data-testid={`manual-${k}`}
                />
              </div>
            ))}
          </div>
          <div>
            <label className="label">מחיר (₪)</label>
            <input className="field ltr" type="number" min={0} value={form.price_ils} onChange={(e) => set('price_ils', e.target.value)} />
          </div>
          <div>
            <label className="label">קישור למוצר</label>
            <input className="field ltr" placeholder="https://…" value={form.product_url} onChange={(e) => set('product_url', e.target.value)} />
          </div>
          <div>
            <label className="label">קישור לתמונה</label>
            <input className="field ltr" placeholder="https://…" value={form.image_url} onChange={(e) => set('image_url', e.target.value)} />
          </div>
          <button className="btn btn-primary w-full" disabled={!valid || saving} onClick={saveManual} data-testid="manual-save">
            {saving ? 'שומר…' : 'הוסף לקטלוג'}
          </button>
        </div>
      </section>
    </div>
  )
}
