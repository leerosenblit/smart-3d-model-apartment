import * as THREE from 'three'
import { cmToM } from './units'

export interface TargetDims {
  width_cm: number
  depth_cm: number
  height_cm: number
}

/**
 * Normalizes an arbitrary Image-to-3D model so it matches real-world dimensions:
 *  1. clone the loaded scene and measure it with Box3
 *  2. scale X/Y/Z so the box equals width/height/depth (cm → m)
 *  3. recenter X/Z to 0 and lift so box.min.y === 0 (bottom-center pivot on the floor)
 *
 * The result is wrapped in a Group so callers can freely position/rotate the wrapper.
 */
export function normalizeGlbModel(scene: THREE.Object3D, dims: TargetDims): THREE.Group {
  const model = scene.clone(true)
  model.position.set(0, 0, 0)
  model.rotation.set(0, 0, 0)
  model.scale.set(1, 1, 1)
  model.updateMatrixWorld(true)

  const box = new THREE.Box3().setFromObject(model)
  const size = box.getSize(new THREE.Vector3())
  const eps = 1e-6
  const sx = cmToM(dims.width_cm) / Math.max(size.x, eps)
  const sy = cmToM(dims.height_cm) / Math.max(size.y, eps)
  const sz = cmToM(dims.depth_cm) / Math.max(size.z, eps)
  model.scale.set(sx, sy, sz)
  model.updateMatrixWorld(true)

  const scaled = new THREE.Box3().setFromObject(model)
  const center = scaled.getCenter(new THREE.Vector3())
  model.position.set(-center.x, -scaled.min.y, -center.z)

  model.traverse((o) => {
    if ((o as THREE.Mesh).isMesh) {
      o.castShadow = true
      o.receiveShadow = true
    }
  })

  const wrapper = new THREE.Group()
  wrapper.name = 'normalized-model'
  wrapper.add(model)
  return wrapper
}
