import type { Category } from '../types'

export const CATEGORY_LABELS: Record<Category, string> = {
  sofa: 'ספות',
  armchair: 'כורסאות',
  tv_unit: 'מזנוני טלוויזיה',
  coffee_table: 'שולחנות סלון',
  dining_table: 'שולחנות אוכל',
  chair: 'כיסאות',
  bed: 'מיטות',
  wardrobe: 'ארונות בגדים',
  storage: 'אחסון ושידות',
  desk: 'שולחנות עבודה',
  appliance: 'מוצרי חשמל',
  lighting: 'תאורה',
  decor: 'עיצוב',
  other: 'אחר',
}

export const CATEGORY_ORDER = Object.keys(CATEGORY_LABELS) as Category[]

export const DND_MIME = 'application/x-roomcraft-product'

export const CATEGORY_COLORS: Record<Category, string> = {
  sofa: '#607d8b',
  armchair: '#a1887f',
  tv_unit: '#8d6e63',
  coffee_table: '#bcaaa4',
  dining_table: '#a1887f',
  chair: '#8d6e63',
  bed: '#7986cb',
  wardrobe: '#90a4ae',
  storage: '#a1887f',
  desk: '#4db6ac',
  appliance: '#78909c',
  lighting: '#fbc02d',
  decor: '#4db6ac',
  other: '#90a4ae',
}
