import { useState } from 'react'
import type { Product } from '../../types'
import { useAppStore } from '../../store/useAppStore'
import { DND_MIME } from '../../utils/labels'
import { formatDims, formatIls } from '../../utils/format'
import { addProductAtCenter } from '../../utils/viewRegistry'

const isRemote = (url: string) => /^https?:\/\//i.test(url)

/** Small product photo: cached backend thumbnail -> original image_url -> neutral placeholder. */
export function ProductThumb({
  productId,
  imageUrl,
  className = '',
}: {
  productId: number
  imageUrl: string
  className?: string
}) {
  // 0 = backend thumbnail (remote photos) / data URI, 1 = original image_url, 2 = placeholder
  const [stage, setStage] = useState(0)
  const remote = isRemote(imageUrl)
  const src =
    !imageUrl || stage >= 2
      ? ''
      : remote && stage === 0
        ? `/api/products/${productId}/image`
        : imageUrl

  return (
    <div className={`relative shrink-0 overflow-hidden rounded-md bg-white ring-1 ring-slate-200 ${className}`}>
      {src ? (
        <img
          key={src}
          src={src}
          alt=""
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          draggable={false}
          className="h-full w-full object-contain"
          onError={() => setStage((s) => (remote && s === 0 ? 1 : 2))}
        />
      ) : (
        <div className="flex h-full w-full items-center justify-center bg-slate-100 text-slate-300" aria-hidden>
          <svg viewBox="0 0 24 24" className="h-8 w-8" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M3 8l9-5 9 5v8l-9 5-9-5V8z" strokeLinejoin="round" />
            <path d="M3 8l9 5 9-5M12 13v8" strokeLinejoin="round" />
          </svg>
        </div>
      )}
    </div>
  )
}

export function ProductCard({ product }: { product: Product }) {
  const ms = useAppStore((s) => s.modelStates[product.id])
  const status = ms?.status ?? product.model_status
  const ready = status === 'ready'
  const generating = status === 'generating'

  return (
    <div
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData(DND_MIME, String(product.id))
        e.dataTransfer.setData('text/plain', product.title)
        e.dataTransfer.effectAllowed = 'copy'
      }}
      className="group flex cursor-grab gap-2 rounded-lg border border-slate-200 bg-white p-2 shadow-sm transition hover:border-brand-500 hover:shadow active:cursor-grabbing"
      title="גררו אל התוכנית או לחצו על הוסף"
      data-testid="product-card"
    >
      <div className="relative shrink-0">
        <ProductThumb productId={product.id} imageUrl={product.image_url} className="h-20 w-24" />
        {ready && (
          <span className="absolute bottom-0.5 start-0.5 rounded bg-emerald-600 px-1 text-[10px] font-bold text-white" title="מודל תלת-ממד שמור">
            3D ✓
          </span>
        )}
        {generating && (
          <span className="absolute bottom-0.5 start-0.5 animate-pulse rounded bg-amber-500 px-1 text-[10px] font-bold text-white">
            ממדל…
          </span>
        )}
      </div>
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="line-clamp-2 text-sm font-semibold leading-tight text-slate-800" title={product.title}>
          {product.title}
        </div>
        <div className="truncate text-[11px] text-slate-500">{product.store_name}</div>
        <div className="ltr mt-0.5 text-start text-[11px] text-slate-600">
          {formatDims(product.width_cm, product.depth_cm, product.height_cm)}
        </div>
        <div className="mt-auto flex items-center justify-between">
          <span className="text-sm font-bold text-brand-700">{formatIls(product.price_ils)}</span>
          <button className="btn btn-primary !px-2 !py-0.5 text-xs" onClick={() => addProductAtCenter(product)}>
            + הוסף
          </button>
        </div>
      </div>
    </div>
  )
}
