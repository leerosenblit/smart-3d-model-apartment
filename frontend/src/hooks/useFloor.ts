import { useMemo } from 'react'
import { useAppStore } from '../store/useAppStore'
import { computeFloor } from '../utils/floorTexture'
import type { FloorResult } from '../utils/floorTexture'

/** Detected rooms + floor texture, recomputed only when walls or room styles change. */
export function useFloor(): FloorResult | null {
  const walls = useAppStore((s) => s.walls)
  const styles = useAppStore((s) => s.roomStyles)
  const openings = useAppStore((s) => s.openings)
  return useMemo(() => computeFloor(walls, styles, openings), [walls, styles, openings])
}
