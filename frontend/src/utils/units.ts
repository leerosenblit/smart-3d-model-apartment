/**
 * Unit conversion. Centimeters are canonical everywhere (store, DB, 2D editor).
 * Meters exist ONLY inside the Three.js / R3F rendering layer — import `cmToM`
 * only from components/viewer3d and utils/normalizeGlbModel.
 */
export const cmToM = (cm: number): number => cm / 100
export const mToCm = (m: number): number => m * 100
export const deg2rad = (d: number): number => (d * Math.PI) / 180
export const rad2deg = (r: number): number => (r * 180) / Math.PI
