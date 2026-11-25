import { useEffect, useRef } from 'react'
import { PointerLockControls } from '@react-three/drei'
import { useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import type { Point } from '../../types'
import { resolveCircleCollisions } from '../../utils/geometry'
import { cmToM, mToCm } from '../../utils/units'

export const EYE_HEIGHT_CM = 160
const RADIUS_CM = 22
const WALK_SPEED = 1.6 // m/s
const RUN_SPEED = 3.6

const MOVE_KEYS: Record<string, 'f' | 'b' | 'l' | 'r' | 'tl' | 'tr'> = {
  KeyW: 'f', ArrowUp: 'f',
  KeyS: 'b', ArrowDown: 'b',
  KeyA: 'l',
  KeyD: 'r',
  KeyQ: 'tl', ArrowLeft: 'tl',
  KeyE: 'tr', ArrowRight: 'tr',
}

/**
 * First-person walk-through: WASD / arrows move, mouse looks (pointer lock), Shift runs.
 * Movement is checked against wall/furniture colliders so you can't walk through walls,
 * but door openings are passable.
 */
export function WalkController({
  start,
  lookAt,
  colliders,
  onLockChange,
}: {
  start: Point
  lookAt: Point
  colliders: Point[][]
  onLockChange: (locked: boolean) => void
}) {
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera
  const keys = useRef(new Set<string>())
  const collidersRef = useRef(colliders)
  collidersRef.current = colliders
  const tmp = useRef({ fwd: new THREE.Vector3(), right: new THREE.Vector3() })

  // place the camera at eye height, facing the middle of the plan
  useEffect(() => {
    const prevFov = camera.fov
    camera.fov = 72
    camera.position.set(cmToM(start.x), cmToM(EYE_HEIGHT_CM), cmToM(start.y))
    const yaw = Math.atan2(-(lookAt.x - start.x), -(lookAt.y - start.y))
    camera.rotation.set(0, Number.isFinite(yaw) ? yaw : 0, 0, 'YXZ')
    camera.updateProjectionMatrix()
    return () => {
      camera.fov = prevFov
      camera.updateProjectionMatrix()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [camera])

  useEffect(() => {
    const typing = (t: EventTarget | null) =>
      t instanceof HTMLElement && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT')
    const down = (e: KeyboardEvent) => {
      if (typing(e.target)) return
      if (e.code in MOVE_KEYS || e.code === 'ShiftLeft' || e.code === 'ShiftRight') {
        keys.current.add(e.code)
        e.preventDefault()
        e.stopPropagation()
      }
    }
    const up = (e: KeyboardEvent) => keys.current.delete(e.code)
    const blur = () => keys.current.clear()
    window.addEventListener('keydown', down, true)
    window.addEventListener('keyup', up)
    window.addEventListener('blur', blur)
    return () => {
      window.removeEventListener('keydown', down, true)
      window.removeEventListener('keyup', up)
      window.removeEventListener('blur', blur)
    }
  }, [])

  useFrame((_, delta) => {
    const k = keys.current
    if (k.size === 0) return
    const dt = Math.min(delta, 0.05)
    let f = 0
    let r = 0
    let turn = 0
    for (const code of k) {
      const m = MOVE_KEYS[code]
      if (m === 'f') f += 1
      else if (m === 'b') f -= 1
      else if (m === 'r') r += 1
      else if (m === 'l') r -= 1
      else if (m === 'tl') turn += 1
      else if (m === 'tr') turn -= 1
    }
    if (turn) camera.rotation.y += turn * 1.6 * dt
    if (!f && !r) return

    const { fwd, right } = tmp.current
    camera.getWorldDirection(fwd)
    fwd.y = 0
    fwd.normalize()
    right.crossVectors(fwd, camera.up).normalize()
    const speed = k.has('ShiftLeft') || k.has('ShiftRight') ? RUN_SPEED : WALK_SPEED
    const dx = (fwd.x * f + right.x * r) * speed * dt
    const dz = (fwd.z * f + right.z * r) * speed * dt
    const target = { x: mToCm(camera.position.x + dx), y: mToCm(camera.position.z + dz) }
    const safe = resolveCircleCollisions(target, RADIUS_CM, collidersRef.current)
    camera.position.set(cmToM(safe.x), cmToM(EYE_HEIGHT_CM), cmToM(safe.y))
  })

  return (
    <PointerLockControls
      selector="[data-testid=viewer3d] canvas"
      onLock={() => onLockChange(true)}
      onUnlock={() => onLockChange(false)}
    />
  )
}
