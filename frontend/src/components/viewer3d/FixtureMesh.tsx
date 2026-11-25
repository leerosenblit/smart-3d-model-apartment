import { Edges } from '@react-three/drei'
import type { FixtureKind } from '../../types'
import { cmToM } from '../../utils/units'

const CERAMIC = '#f6f7f8'
const CHROME = '#b9bfc6'

/** Metric helper: all sizes are given in cm and converted here (meters live only in the 3D layer). */
const m = cmToM

interface Props {
  kind: FixtureKind
  widthCm: number
  depthCm: number
  heightCm: number
}

/**
 * Procedural bathroom / utility fixtures for the 3D preview. Local frame matches placed items:
 * origin at bottom-center on the floor, back (against the wall) at -z, front at +z.
 */
export function FixtureMesh({ kind, widthCm, depthCm, heightCm }: Props) {
  const w = m(widthCm)
  const d = m(depthCm)
  const h = m(heightCm)

  switch (kind) {
    case 'toilet': {
      const tankD = d * 0.28
      return (
        <group>
          {/* cistern against the wall */}
          <mesh position={[0, h * 0.62, -d / 2 + tankD / 2]} castShadow receiveShadow>
            <boxGeometry args={[w * 0.92, h * 0.52, tankD]} />
            <meshStandardMaterial color={CERAMIC} roughness={0.25} />
          </mesh>
          {/* pedestal + bowl */}
          <mesh position={[0, h * 0.2, -d * 0.1]} castShadow>
            <boxGeometry args={[w * 0.45, h * 0.4, d * 0.5]} />
            <meshStandardMaterial color={CERAMIC} roughness={0.25} />
          </mesh>
          <mesh position={[0, h * 0.44, d * 0.12]} scale={[1, 0.38, 1.28]} castShadow>
            <cylinderGeometry args={[w * 0.46, w * 0.38, d * 0.55, 28]} />
            <meshStandardMaterial color={CERAMIC} roughness={0.25} />
          </mesh>
          {/* seat */}
          <mesh position={[0, h * 0.5, d * 0.12]} scale={[1, 1, 1.28]}>
            <cylinderGeometry args={[w * 0.43, w * 0.43, d * 0.03, 28]} />
            <meshStandardMaterial color="#e3e6e8" roughness={0.4} />
          </mesh>
          <mesh position={[w * 0.28, h * 0.9, -d / 2 + tankD * 0.6]}>
            <cylinderGeometry args={[w * 0.05, w * 0.05, h * 0.03, 16]} />
            <meshStandardMaterial color={CHROME} metalness={0.7} roughness={0.3} />
          </mesh>
        </group>
      )
    }
    case 'sink': {
      const counter = h * 0.94
      return (
        <group>
          {/* vanity cabinet */}
          <mesh position={[0, counter / 2, 0]} castShadow receiveShadow>
            <boxGeometry args={[w, counter, d]} />
            <meshStandardMaterial color="#d8c7ae" roughness={0.55} />
            <Edges color="#8a7a63" />
          </mesh>
          {/* ceramic top + basin */}
          <mesh position={[0, counter + h * 0.015, 0]}>
            <boxGeometry args={[w * 1.02, h * 0.03, d * 1.02]} />
            <meshStandardMaterial color={CERAMIC} roughness={0.25} />
          </mesh>
          <mesh position={[0, counter + h * 0.034, d * 0.06]} scale={[1, 0.25, 0.8]}>
            <cylinderGeometry args={[w * 0.32, w * 0.26, d * 0.55, 28]} />
            <meshStandardMaterial color="#e9eef1" roughness={0.2} />
          </mesh>
          {/* tap */}
          <mesh position={[0, counter + h * 0.1, -d * 0.3]}>
            <cylinderGeometry args={[w * 0.025, w * 0.025, h * 0.14, 12]} />
            <meshStandardMaterial color={CHROME} metalness={0.8} roughness={0.2} />
          </mesh>
          <mesh position={[0, counter + h * 0.165, -d * 0.2]}>
            <boxGeometry args={[w * 0.04, h * 0.02, d * 0.22]} />
            <meshStandardMaterial color={CHROME} metalness={0.8} roughness={0.2} />
          </mesh>
          {/* mirror on the wall */}
          <mesh position={[0, counter + h * 0.55, -d / 2 + 0.01]}>
            <boxGeometry args={[w * 0.9, h * 0.55, 0.015]} />
            <meshStandardMaterial color="#cfe6ee" metalness={0.9} roughness={0.08} />
          </mesh>
        </group>
      )
    }
    case 'bathtub': {
      const rim = h
      return (
        <group>
          <mesh position={[0, rim / 2, 0]} castShadow receiveShadow>
            <boxGeometry args={[w, rim, d]} />
            <meshStandardMaterial color={CERAMIC} roughness={0.25} />
          </mesh>
          {/* inner basin (slightly lower, tinted) */}
          <mesh position={[0, rim - 0.004, 0]}>
            <boxGeometry args={[w * 0.9, 0.01, d * 0.8]} />
            <meshStandardMaterial color="#cfe5ee" roughness={0.1} />
          </mesh>
          {/* tap at the head end */}
          <mesh position={[-w / 2 + w * 0.06, rim + h * 0.1, 0]}>
            <cylinderGeometry args={[d * 0.025, d * 0.025, h * 0.22, 12]} />
            <meshStandardMaterial color={CHROME} metalness={0.8} roughness={0.2} />
          </mesh>
        </group>
      )
    }
    case 'shower': {
      const glass = h
      return (
        <group>
          <mesh position={[0, 0.03, 0]} receiveShadow>
            <boxGeometry args={[w, 0.06, d]} />
            <meshStandardMaterial color="#e8ebed" roughness={0.5} />
          </mesh>
          {/* glass panels on the two open sides (front and side) */}
          <mesh position={[0, glass / 2, d / 2 - 0.01]}>
            <boxGeometry args={[w, glass, 0.012]} />
            <meshPhysicalMaterial color="#cfe9f2" transparent opacity={0.22} roughness={0.05} depthWrite={false} />
          </mesh>
          <mesh position={[w / 2 - 0.01, glass / 2, 0]}>
            <boxGeometry args={[0.012, glass, d]} />
            <meshPhysicalMaterial color="#cfe9f2" transparent opacity={0.22} roughness={0.05} depthWrite={false} />
          </mesh>
          {/* rain head + arm */}
          <mesh position={[0, glass * 0.97, -d * 0.3]} rotation-x={Math.PI / 2}>
            <cylinderGeometry args={[w * 0.2, w * 0.2, 0.02, 24]} />
            <meshStandardMaterial color={CHROME} metalness={0.8} roughness={0.25} />
          </mesh>
        </group>
      )
    }
    case 'washer':
      return (
        <group>
          <mesh position={[0, h / 2, 0]} castShadow receiveShadow>
            <boxGeometry args={[w, h, d]} />
            <meshStandardMaterial color="#f1f3f5" roughness={0.35} />
          </mesh>
          <mesh position={[0, h * 0.5, d / 2 + 0.001]} rotation-x={Math.PI / 2}>
            <cylinderGeometry args={[w * 0.3, w * 0.3, 0.01, 28]} />
            <meshStandardMaterial color="#4a5560" metalness={0.6} roughness={0.15} />
          </mesh>
        </group>
      )
    default:
      return null
  }
}
