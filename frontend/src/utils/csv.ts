import type { PlacedItem } from '../types'

export interface BomLine {
  productId: number
  title: string
  storeName: string
  productUrl: string
  category: string
  qty: number
  unitPrice: number
  subtotal: number
  widthCm: number
  depthCm: number
  heightCm: number
}

export function buildBom(items: PlacedItem[]): BomLine[] {
  const map = new Map<number, BomLine>()
  for (const it of items) {
    const line = map.get(it.productId)
    if (line) {
      line.qty += 1
      line.subtotal += it.priceIls
    } else {
      map.set(it.productId, {
        productId: it.productId,
        title: it.title,
        storeName: it.storeName,
        productUrl: it.productUrl,
        category: it.category,
        qty: 1,
        unitPrice: it.priceIls,
        subtotal: it.priceIls,
        widthCm: it.widthCm,
        depthCm: it.depthCm,
        heightCm: it.heightCm,
      })
    }
  }
  return [...map.values()]
}

const esc = (v: string | number): string => {
  const s = String(v)
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

export function bomToCsv(lines: BomLine[]): string {
  const header = ['מוצר', 'חנות', 'קטגוריה', 'כמות', 'מחיר ליחידה (₪)', 'סכום (₪)', 'רוחב (ס"מ)', 'עומק (ס"מ)', 'גובה (ס"מ)', 'קישור']
  const rows = lines.map((l) => [
    l.title, l.storeName, l.category, l.qty, l.unitPrice, l.subtotal, l.widthCm, l.depthCm, l.heightCm, l.productUrl,
  ])
  const total = lines.reduce((s, l) => s + l.subtotal, 0)
  rows.push(['סה"כ', '', '', lines.reduce((s, l) => s + l.qty, 0), '', total, '', '', '', ''])
  return [header, ...rows].map((r) => r.map(esc).join(',')).join('\r\n')
}

/** Download with a UTF-8 BOM so Excel renders Hebrew correctly. */
export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob(['﻿', csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
