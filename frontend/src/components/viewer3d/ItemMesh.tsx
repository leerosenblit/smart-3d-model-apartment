import { Component, Suspense, useMemo } from 'react'
import type { ReactNode } from 'react'
import type { ThreeEvent } from '@react-three/fiber'
import { useThree } from '@react-three/fiber'
import { Edges, Html, useGLTF } from '@react-three/drei'
import { useAppStore } from '../../store/useAppStore'
import type { PlacedItem } from '../../types'
import { CATEGORY_COLORS } from '../../utils/labels'
import { normalizeGlbModel } from '../../utils/normalizeGlbModel'
import { cmToM, deg2rad } from '../../utils/units'
import { FixtureMesh } from './FixtureMesh'
import { drag3d, rayToFloorCm, walkState } from './floor'

const BRAND = '#2f7de1'

class ModelBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  componentDidCatch(err: unknown) {
    console.warn('GLB failed to load; keeping placeholder box', err)
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children
  }
}

function Placeholder({ item, status }: { item: PlacedItem; status?: string }) {
  const w = cmToM(item.widthCm)
  const h = cmToM(item.heightCm)
  const d = cmToM(item.depthCm)
  const color = CATEGORY_COLORS[item.category] ?? '#90a4ae'
  const generating = status === 'generating' || status === 'none' || status === undefined
  return (
    <group>
      <mesh position={[0, h / 2, 0]} castShadow>
        <boxGeometry args={[w, h, d]} />
        <meshStandardMaterial color={color} transparent opacity={0.38} depthWrite={false} />
        <Edges color="#0f172a" />
      </mesh>
      <Html
        position={[0, h + 0.12, 0]}
        center
        zIndexRange={[20, 0]}
        style={{ pointerEvents: 'none', whiteSpace: 'nowrap' }}
      >
        <div className="flex flex-col items-center gap-0.5 text-center" dir="rtl">
          <span className="rounded bg-white/90 px-1.5 py-0.5 text-[11px] font-bold text-slate-800 shadow">{item.title}</span>
          {status === 'failed' ? (
            <span className="rounded-full bg-red-500/90 px-2 py-0.5 text-[10px] font-semibold text-white">מודל תלת-ממד נכשל</span>
          ) : generating ? (
            <span className="animate-pulse rounded-full bg-amber-500/90 px-2 py-0.5 text-[10px] font-semibold text-white" data-testid="modeling-pill">
              ממדל 3D...
            </span>
          ) : null}
        </div>
      </Html>
    </group>
  )
}

function ModelBody({ item, url }: { item: PlacedItem; url: string }) {
  const gltf = useGLTF(url, false)
  const model = useMemo(
    () =>
      normalizeGlbModel(gltf.scene, {
        width_cm: item.widthCm,
        depth_cm: item.depthCm,
        height_cm: item.heightCm,
      }),
    [gltf.scene, item.widthCm, item.depthCm, item.heightCm],
  )
  return <primitive object={model} />
}

export function ItemMesh({ item }: { item: PlacedItem }) {
  const ms = useAppStore((s) => s.modelStates[item.productId])
  const selected = useAppStore((s) => s.selected?.type === 'item' && s.selected.id === item.id)
  const controls = useThree((s) => s.controls) as unknown as { enabled: boolean } | null

  const w = cmToM(item.widthCm)
  const h = cmToM(item.heightCm)
  const d = cmToM(item.depthCm)
  const status = ms?.status
  const ready = status === 'ready' && !!ms?.url

  const onPointerDown = (e: ThreeEvent<PointerEvent>) => {
    if (e.button !== 0 || walkState.active) return
    e.stopPropagation()
    const st = useAppStore.getState()
    st.setSelected({ type: 'item', id: item.id })
    const p = rayToFloorCm(e.ray)
    if (!p) return
    st.pushHistory() // one undo entry per drag gesture
    drag3d.id = item.id
    drag3d.offX = p.x - item.xCm
    drag3d.offY = p.y - item.zCm
    if (controls) controls.enabled = false
  }

  return (
    <group
      position={[cmToM(item.xCm), 0, cmToM(item.zCm)]}
      // plan rotation is clockwise-on-screen; three.js rotation.y is the opposite sense
      rotation={[0, -deg2rad(item.rotationDeg), 0]}
      onPointerDown={onPointerDown}
      // clicks on an item must not fall through to the floor/walls behind it (which would deselect)
      onClick={(e) => e.stopPropagation()}
      userData={{ itemId: item.id }}
    >
      {item.fixture ? (
        <FixtureMesh kind={item.fixture} widthCm={item.widthCm} depthCm={item.depthCm} heightCm={item.heightCm} />
      ) : ready ? (
        <ModelBoundary fallback={<Placeholder item={item} status="failed" />}>
          <Suspense fallback={<Placeholder item={item} status="generating" />}>
            <ModelBody item={item} url={ms!.url!} />
          </Suspense>
        </ModelBoundary>
      ) : (
        <Placeholder item={item} status={status} />
      )}
      {selected && (
        <mesh position={[0, h / 2, 0]}>
          <boxGeometry args={[w, h, d]} />
          <meshBasicMaterial transparent opacity={0} depthWrite={false} />
          <Edges color={BRAND} lineWidth={2} />
        </mesh>
      )}
    </group>
  )
}
