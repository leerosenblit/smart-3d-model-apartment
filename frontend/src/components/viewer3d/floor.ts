import * as THREE from 'three'
import type { Point } from '../../types'
import { mToCm } from '../../utils/units'

const floorPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0) // y = 0
const raycaster = new THREE.Raycaster()
const hit = new THREE.Vector3()

/** Intersect a ray with the floor plane (y = 0). Returns plan cm (x, y→world z) or null. */
export function rayToFloorCm(ray: THREE.Ray): Point | null {
  if (!ray.intersectPlane(floorPlane, hit)) return null
  return { x: mToCm(hit.x), y: mToCm(hit.z) }
}

export function clientToFloorCm(
  clientX: number,
  clientY: number,
  dom: HTMLElement,
  camera: THREE.Camera,
): Point | null {
  const r = dom.getBoundingClientRect()
  const ndc = new THREE.Vector2(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1)
  raycaster.setFromCamera(ndc, camera)
  return rayToFloorCm(raycaster.ray)
}

/** Shared drag state for dragging an item along the floor in 3D. */
export const drag3d: { id: string | null; offX: number; offY: number } = { id: null, offX: 0, offY: 0 }

/** Set by <DropBridge/> inside the Canvas so HTML drops can be converted to floor points. */
export const dropBridge: { toFloor: ((clientX: number, clientY: number) => Point | null) | null } = {
  toFloor: null,
}

/** True while the first-person walk-through is active (disables item dragging / wall picking). */
export const walkState = { active: false }
