import { useMemo } from 'react'
import * as THREE from 'three'
import { useAppStore } from '../../store/useAppStore'
import type { Opening, Wall } from '../../types'
import { computeWallCutouts, wallAngle, wallDir, wallLength } from '../../utils/geometry'
import { cmToM } from '../../utils/units'
import { walkState } from './floor'

/**
 * Extruded wall with real cutouts. Local frame: x along the wall (start → end), y up, z thickness.
 * Doors are notches carved from the bottom edge; windows are holes with sill height, so the wall
 * above (lintel) and below (sill) stays solid. Each end is extended by half the thickness so
 * corners meet cleanly.
 */
export function WallMesh({ wall, openings, ceilingHeightCm }: { wall: Wall; openings: Opening[]; ceilingHeightCm: number }) {
  const selected = useAppStore((s) => s.selected?.type === 'wall' && s.selected.id === wall.id)

  const { geometry, windows, solids, thickness, position, rotationY } = useMemo(() => {
    const t = wall.thicknessCm
    const ext = t / 2
    const length = wallLength(wall) + t
    const H = ceilingHeightCm
    const shifted = openings.map((o) => ({ ...o, offsetCm: o.offsetCm + ext }))
    const cut = computeWallCutouts(shifted, length, H)

    const shape = new THREE.Shape()
    shape.moveTo(0, 0)
    for (const n of [...cut.notches].sort((a, b) => a.x0 - b.x0)) {
      shape.lineTo(cmToM(n.x0), 0)
      shape.lineTo(cmToM(n.x0), cmToM(n.top))
      shape.lineTo(cmToM(n.x1), cmToM(n.top))
      shape.lineTo(cmToM(n.x1), 0)
    }
    shape.lineTo(cmToM(length), 0)
    shape.lineTo(cmToM(length), cmToM(H))
    shape.lineTo(0, cmToM(H))
    shape.closePath()
    for (const h of cut.holes) {
      const p = new THREE.Path()
      p.moveTo(cmToM(h.x0), cmToM(h.y0))
      p.lineTo(cmToM(h.x1), cmToM(h.y0))
      p.lineTo(cmToM(h.x1), cmToM(h.y1))
      p.lineTo(cmToM(h.x0), cmToM(h.y1))
      p.closePath()
      shape.holes.push(p)
    }
    const geo = new THREE.ExtrudeGeometry(shape, { depth: cmToM(t), bevelEnabled: false })
    geo.translate(0, 0, -cmToM(t) / 2)

    // wall stretches that touch the floor (everything except door notches) get a baseboard
    const solids: [number, number][] = []
    let cursor = 0
    for (const n of [...cut.notches].sort((a, b) => a.x0 - b.x0)) {
      if (n.x0 > cursor + 1) solids.push([cursor, n.x0])
      cursor = n.x1
    }
    if (length > cursor + 1) solids.push([cursor, length])

    const d = wallDir(wall)
    return {
      geometry: geo,
      windows: cut.holes,
      solids,
      thickness: t,
      position: [cmToM(wall.x1 - d.x * ext), 0, cmToM(wall.y1 - d.y * ext)] as [number, number, number],
      // plan angle φ (clockwise on screen) ↔ three.js rotation.y = -φ
      rotationY: -wallAngle(wall),
    }
  }, [wall, openings, ceilingHeightCm])

  const useSelect = () => useAppStore.getState().setSelected({ type: 'wall', id: wall.id })

  return (
    <group position={position} rotation={[0, rotationY, 0]}>
      <mesh
        geometry={geometry}
        castShadow
        receiveShadow
        onClick={(e) => {
          e.stopPropagation()
          if (e.delta <= 2 && !walkState.active) useSelect()
        }}
      >
        <meshStandardMaterial color="#f7f5f1" roughness={0.95} emissive={selected ? '#2f7de1' : '#000000'} emissiveIntensity={selected ? 0.35 : 0} />
      </mesh>
      {solids.map(([a, b], i) =>
        [1, -1].map((side) => (
          <mesh key={`bb-${i}-${side}`} position={[cmToM((a + b) / 2), 0.04, side * cmToM(thickness / 2 + 0.6)]} castShadow receiveShadow>
            <boxGeometry args={[cmToM(b - a), 0.08, cmToM(1.2)]} />
            <meshStandardMaterial color="#ffffff" roughness={0.45} />
          </mesh>
        )),
      )}
      {windows.map((h, i) => (
        <mesh key={i} position={[cmToM((h.x0 + h.x1) / 2), cmToM((h.y0 + h.y1) / 2), 0]}>
          <boxGeometry args={[cmToM(h.x1 - h.x0), cmToM(h.y1 - h.y0), 0.012]} />
          <meshPhysicalMaterial color="#bfe3f5" transparent opacity={0.28} roughness={0.05} depthWrite={false} />
        </mesh>
      ))}
    </group>
  )
}
