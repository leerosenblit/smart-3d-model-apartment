const ilsFmt = new Intl.NumberFormat('he-IL', { maximumFractionDigits: 0 })

/** `₪1,990` */
export function formatIls(value: number): string {
  return `₪${ilsFmt.format(Math.round(value))}`
}

/** Strip trailing zeros: 220 → "220", 87.5 → "87.5" */
export function formatCm(value: number, digits = 1): string {
  return String(Number(value.toFixed(digits)))
}

/** `228×95×83 ס"מ` (W×D×H) */
export function formatDims(w: number, d: number, h: number): string {
  return `${formatCm(w)}×${formatCm(d)}×${formatCm(h)} ס"מ`
}

export function uid(prefix = 'id'): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 9)}${Date.now().toString(36).slice(-3)}`
}
