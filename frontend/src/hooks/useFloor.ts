import { useMemo } from 'react'
import { useAppStore } from '../store/useAppStore'
import { computeFloor } from '../utils/floorTexture'
import type { FloorResult } from '../utils/floorTexture'

/** Detected rooms + floor texture, recomputed only when walls or room styles change. */
export function useFloor(): FloorResult | null {
  const walls = useAppStore((s) => s.walls)
  const styles = useAppStore((s) => s.roomStyles)
  return useMemo(() => computeFloor(walls, styles), [walls, styles])
}
