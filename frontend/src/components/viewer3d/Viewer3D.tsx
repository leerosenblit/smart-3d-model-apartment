import { useEffect, useMemo, useState } from 'react'
import { Canvas, useThree } from '@react-three/fiber'
import { ContactShadows, Environment, Grid, Html, Lightformer, Line, OrbitControls } from '@react-three/drei'
import * as THREE from 'three'
import { useFloor } from '../../hooks/useFloor'
import { placeProduct } from '../../hooks/useModelGeneration'
import { useAppStore } from '../../store/useAppStore'
import { isProductDrag, resolveDroppedProduct } from '../../utils/dropProduct'
import { formatCm } from '../../utils/format'
import {
  buildWalkColliders,
  computeClearances,
  findWalkStart,
  resolveCircleCollisions,
  roundTo,
  sceneBounds,
  snapItemToWalls,
} from '../../utils/geometry'
import type { Point } from '../../types'
import { roomAt, roomKey } from '../../utils/rooms'
import { cmToM } from '../../utils/units'
import { ItemMesh } from './ItemMesh'
import { WallMesh } from './WallMesh'
import { clientToFloorCm, drag3d, dropBridge, walkState } from './floor'
import { WalkController } from './WalkController'

const GRID_STEP = 5

function Lights() {
  return (
    <>
      <hemisphereLight args={['#ffffff', '#d9d3c7', 0.55]} />
      <ambientLight intensity={0.25} />
      <directionalLight
        position={[6, 11, 7]}
        intensity={1.4}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-14}
        shadow-camera-right={14}
        shadow-camera-top={14}
        shadow-camera-bottom={-14}
        shadow-bias={-0.0004}
      />
      {/* procedural studio environment — no network fetch required */}
      <Environment resolution={256}>
        <Lightformer form="rect" intensity={2.2} position={[0, 6, -6]} scale={[14, 6, 1]} />
        <Lightformer form="rect" intensity={1.4} position={[-6, 4, 4]} scale={[6, 6, 1]} />
        <Lightformer form="rect" intensity={1.2} position={[6, 3, 5]} scale={[6, 4, 1]} />
        <Lightformer form="ring" intensity={1.5} position={[0, 8, 0]} scale={6} rotation-x={Math.PI / 2} />
      </Environment>
    </>
  )
}

function Floor({ onWalkAt }: { onWalkAt: (p: Point) => void }) {
  const setSelected = useAppStore((s) => s.setSelected)
  const hasFloor = useFloor() !== null
  return (
    <>
      <mesh
        rotation-x={-Math.PI / 2}
        position={[0, -0.002, 0]}
        receiveShadow
        onClick={(e) => {
          if (e.delta <= 2) setSelected(null) // a real click, not the end of an orbit/drag gesture
        }}
        onDoubleClick={(e) => {
          if (!walkState.active) onWalkAt({ x: e.point.x * 100, y: e.point.z * 100 }) // double-click the floor to walk from there
        }}
      >
        <planeGeometry args={[120, 120]} />
        <meshStandardMaterial color={hasFloor ? '#dfe3e8' : '#e9e5dc'} roughness={1} />
      </mesh>
      {!hasFloor && (
        <Grid
          position={[0, 0.001, 0]}
          args={[80, 80]}
          cellSize={0.5}
          cellThickness={0.6}
          cellColor="#cfc9bd"
          sectionSize={1}
          sectionThickness={1}
          sectionColor="#b3ab9b"
          fadeDistance={35}
          fadeStrength={1.5}
          infiniteGrid
        />
      )}
    </>
  )
}

/** Detected rooms painted with wood / tile / concrete / carpet textures (one canvas texture for the whole plan). */
function RoomFloor({ onWalkAt }: { onWalkAt: (p: Point) => void }) {
  const floor = useFloor()
  const gl = useThree((s) => s.gl)
  const showFloors = useAppStore((s) => s.showFloors)
  const setSelected = useAppStore((s) => s.setSelected)
  const texture = useMemo(() => {
    if (!floor) return null
    const t = new THREE.CanvasTexture(floor.canvas)
    t.colorSpace = THREE.SRGBColorSpace
    t.anisotropy = gl.capabilities.getMaxAnisotropy()
    t.needsUpdate = true
    return t
  }, [floor, gl])
  useEffect(() => () => texture?.dispose(), [texture])
  if (!floor || !texture || !showFloors) return null

  const toPlan = (e: { point: THREE.Vector3 }) => ({ x: e.point.x * 100, y: e.point.z * 100 })
  return (
    <mesh
      position={[cmToM(floor.originX + floor.widthCm / 2), 0.002, cmToM(floor.originY + floor.heightCm / 2)]}
      rotation-x={-Math.PI / 2}
      receiveShadow
      onClick={(e) => {
        e.stopPropagation()
        if (e.delta > 2 || walkState.active) return
        const p = toPlan(e)
        const id = roomAt(floor.layout, p.x, p.y)
        const room = floor.layout.rooms[id]
        setSelected(room ? { type: 'room', id: roomKey(room) } : null)
      }}
      onDoubleClick={(e) => {
        e.stopPropagation()
        if (!walkState.active) onWalkAt(toPlan(e))
      }}
    >
      <planeGeometry args={[cmToM(floor.widthCm), cmToM(floor.heightCm)]} />
      <meshStandardMaterial map={texture} alphaTest={0.35} roughness={0.55} metalness={0} />
    </mesh>
  )
}

/** The uploaded floorplan, laid flat on the floor so you can compare 3D with the original. */
function FloorplanDecal() {
  const url = useAppStore((s) => s.floorplanUrl)
  const visible = useAppStore((s) => s.floorplanVisible)
  const opacity = useAppStore((s) => s.floorplanOpacity)
  const size = useAppStore((s) => s.floorplanSize)
  const ppc = useAppStore((s) => s.pixelsPerCm)
  const hasFloor = useFloor() !== null
  const [tex, setTex] = useState<THREE.Texture | null>(null)

  useEffect(() => {
    if (!url) {
      setTex(null)
      return
    }
    let alive = true
    new THREE.TextureLoader().load(
      url,
      (t) => {
        t.colorSpace = THREE.SRGBColorSpace
        t.anisotropy = 8
        if (alive) setTex(t)
      },
      undefined,
      () => alive && setTex(null),
    )
    return () => {
      alive = false
    }
  }, [url])

  if (!tex || !visible || !size || hasFloor) return null // textured room floors replace the flat plan image
  const effPpc = ppc ?? size.w / 1200
  const wM = cmToM(size.w / effPpc)
  const hM = cmToM(size.h / effPpc)
  return (
    <mesh position={[wM / 2, 0.003, hM / 2]} rotation-x={-Math.PI / 2} renderOrder={1}>
      <planeGeometry args={[wM, hM]} />
      <meshBasicMaterial map={tex} transparent opacity={Math.min(0.85, opacity)} depthWrite={false} toneMapped={false} />
    </mesh>
  )
}

/** Drag the selected item along the floor plane (y = 0), with grid + wall snapping. */
function DragController() {
  const camera = useThree((s) => s.camera)
  const gl = useThree((s) => s.gl)
  const controls = useThree((s) => s.controls) as unknown as { enabled: boolean } | null

  useEffect(() => {
    dropBridge.toFloor = (cx, cy) => clientToFloorCm(cx, cy, gl.domElement, camera)
    return () => {
      dropBridge.toFloor = null
    }
  }, [camera, gl])

  useEffect(() => {
    const move = (e: PointerEvent) => {
      if (!drag3d.id) return
      const st = useAppStore.getState()
      const it = st.placedItems.find((i) => i.id === drag3d.id)
      const p = clientToFloorCm(e.clientX, e.clientY, gl.domElement, camera)
      if (!it || !p) return
      let q = { x: p.x - drag3d.offX, y: p.y - drag3d.offY }
      if (!e.altKey) {
        if (st.gridSnap) q = { x: roundTo(q.x, GRID_STEP), y: roundTo(q.y, GRID_STEP) }
        q = snapItemToWalls({ ...it, xCm: q.x, zCm: q.y }, st.walls, 8)
      }
      st.moveItemLive(it.id, Math.round(q.x * 10) / 10, Math.round(q.y * 10) / 10)
    }
    const up = () => {
      if (!drag3d.id) return
      drag3d.id = null
      if (controls) controls.enabled = true
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    window.addEventListener('pointercancel', up)
    return () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      window.removeEventListener('pointercancel', up)
    }
  }, [camera, gl, controls])

  return null
}

function CameraRig({ fitKey, topDown }: { fitKey: number; topDown: boolean }) {
  const camera = useThree((s) => s.camera)
  const controls = useThree((s) => s.controls) as unknown as { target: THREE.Vector3; update: () => void } | null
  const projectId = useAppStore((s) => s.projectId)
  const hasWalls = useAppStore((s) => s.walls.length > 0) // re-frame when the first walls appear

  useEffect(() => {
    if (!controls) return
    const st = useAppStore.getState()
    const b = sceneBounds(st)
    const cx = cmToM((b.minX + b.maxX) / 2)
    const cz = cmToM((b.minY + b.maxY) / 2)
    const span = Math.max(cmToM(b.maxX - b.minX), cmToM(b.maxY - b.minY), 3)
    controls.target.set(cx, 0.6, cz)
    if (topDown) camera.position.set(cx, span * 1.5 + 2, cz + 0.001)
    else camera.position.set(cx + span * 0.55, span * 0.95 + 1.5, cz + span * 0.95 + 1)
    camera.updateProjectionMatrix()
    controls.update()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitKey, topDown, projectId, controls, hasWalls])
  return null
}

function ClearanceOverlay() {
  const selected = useAppStore((s) => s.selected)
  const walls = useAppStore((s) => s.walls)
  const items = useAppStore((s) => s.placedItems)
  const item = selected?.type === 'item' ? items.find((i) => i.id === selected.id) : undefined
  const list = useMemo(() => (item ? computeClearances(item, { walls, placedItems: items }) : []), [item, walls, items])
  return (
    <>
      {list.map((c) => {
        const a = new THREE.Vector3(cmToM(c.from.x), 0.03, cmToM(c.from.y))
        const b = new THREE.Vector3(cmToM(c.to.x), 0.03, cmToM(c.to.y))
        const mid = a.clone().add(b).multiplyScalar(0.5)
        return (
          <group key={c.side}>
            <Line points={[a, b]} color="#f97316" lineWidth={2} dashed dashSize={0.08} gapSize={0.05} />
            <Html position={[mid.x, 0.1, mid.z]} center zIndexRange={[20, 0]} style={{ pointerEvents: 'none' }}>
              <span className="rounded bg-orange-500 px-1 text-[10px] font-bold text-white shadow">{formatCm(c.cm, 0)} ס"מ</span>
            </Html>
          </group>
        )
      })}
    </>
  )
}

/** Ceiling shown only while walking (it would hide the plan from the orbit camera). */
function Ceiling() {
  const walls = useAppStore((s) => s.walls)
  const items = useAppStore((s) => s.placedItems)
  const ceiling = useAppStore((s) => s.ceilingHeightCm)
  const b = sceneBounds({ walls, placedItems: items })
  const w = cmToM(b.maxX - b.minX) + 1
  const d = cmToM(b.maxY - b.minY) + 1
  return (
    <mesh position={[cmToM((b.minX + b.maxX) / 2), cmToM(ceiling), cmToM((b.minY + b.maxY) / 2)]} rotation-x={Math.PI / 2}>
      <planeGeometry args={[w, d]} />
      <meshStandardMaterial color="#f8f6f1" roughness={1} emissive="#f8f6f1" emissiveIntensity={0.5} />
    </mesh>
  )
}

function SceneContents() {
  const walls = useAppStore((s) => s.walls)
  const openings = useAppStore((s) => s.openings)
  const items = useAppStore((s) => s.placedItems)
  const ceiling = useAppStore((s) => s.ceilingHeightCm)
  const openingsByWall = useMemo(() => {
    const m = new Map<string, typeof openings>()
    for (const o of openings) m.set(o.wallId, [...(m.get(o.wallId) ?? []), o])
    return m
  }, [openings])

  return (
    <>
      {walls.map((w) => (
        <WallMesh key={w.id} wall={w} openings={openingsByWall.get(w.id) ?? []} ceilingHeightCm={ceiling} />
      ))}
      {items.map((it) => (
        <ItemMesh key={it.id} item={it} />
      ))}
      <ClearanceOverlay />
    </>
  )
}

export function Viewer3D() {
  const [fitKey, setFitKey] = useState(0)
  const [topDown, setTopDown] = useState(false)
  const [dropActive, setDropActive] = useState(false)
  const [walk, setWalk] = useState<{ start: Point; lookAt: Point } | null>(null)
  const [locked, setLocked] = useState(false)
  const setSelected = useAppStore((s) => s.setSelected)
  const walls = useAppStore((s) => s.walls)
  const openings = useAppStore((s) => s.openings)
  const items = useAppStore((s) => s.placedItems)
  const colliders = useMemo(
    () => buildWalkColliders({ walls, openings, placedItems: items }),
    [walls, openings, items],
  )

  useEffect(() => {
    walkState.active = walk !== null
    return () => {
      walkState.active = false
    }
  }, [walk])

  const startWalk = (at?: Point) => {
    const st = useAppStore.getState()
    const b = sceneBounds(st)
    const center = { x: (b.minX + b.maxX) / 2, y: (b.minY + b.maxY) / 2 }
    const colls = buildWalkColliders(st)
    const wallsOnly = buildWalkColliders({ walls: st.walls, openings: st.openings, placedItems: [] })
    const start = resolveCircleCollisions(at ?? findWalkStart(wallsOnly, b, center), 30, colls)
    setSelected(null)
    setLocked(false)
    setWalk({ start, lookAt: Math.hypot(center.x - start.x, center.y - start.y) > 50 ? center : { x: start.x, y: start.y - 100 } })
  }

  const onDrop = async (e: React.DragEvent) => {
    e.preventDefault()
    setDropActive(false)
    const p = await resolveDroppedProduct(e.dataTransfer)
    const pt = dropBridge.toFloor?.(e.clientX, e.clientY)
    if (!p || !pt) return
    placeProduct(p, roundTo(pt.x, GRID_STEP), roundTo(pt.y, GRID_STEP))
  }

  return (
    <div
      className={`relative h-full w-full bg-slate-200 ${dropActive ? 'ring-4 ring-inset ring-brand-500/50' : ''}`}
      data-testid="viewer3d"
      onDragOver={(e) => {
        if (isProductDrag(e)) {
          e.preventDefault()
          e.dataTransfer.dropEffect = 'copy'
          setDropActive(true)
        }
      }}
      onDragLeave={() => setDropActive(false)}
      onDrop={onDrop}
    >
      <Canvas
        shadows
        dpr={[1, 2]}
        camera={{ fov: 45, near: 0.1, far: 300, position: [8, 9, 11] }}
        gl={{ antialias: true, preserveDrawingBuffer: true }}
        onPointerMissed={() => !drag3d.id && setSelected(null)}
      >
        <color attach="background" args={['#dfe6ee']} />
        <Lights />
        <Floor onWalkAt={startWalk} />
        <RoomFloor onWalkAt={startWalk} />
        {!walk && <FloorplanDecal />}
        {walk && <Ceiling />}
        <SceneContents />
        <ContactShadows position={[0, 0.004, 0]} opacity={0.35} scale={40} blur={2.2} far={3} resolution={1024} />
        <DragController />
        {walk ? (
          <WalkController start={walk.start} lookAt={walk.lookAt} colliders={colliders} onLockChange={setLocked} />
        ) : (
          <>
            <OrbitControls makeDefault maxPolarAngle={Math.PI / 2 - 0.02} minDistance={1} maxDistance={60} enableDamping />
            <CameraRig fitKey={fitKey} topDown={topDown} />
          </>
        )}
      </Canvas>

      <div className="absolute start-2 top-2 flex gap-1">
        {walk ? (
          <button className="btn btn-primary" onClick={() => setWalk(null)} data-testid="exit-walk">
            ✕ יציאה ממצב הליכה
          </button>
        ) : (
          <button className="btn btn-primary" onClick={() => startWalk()} data-testid="start-walk" title="טיול בדירה בגוף ראשון (או דאבל-קליק על הרצפה)">
            🚶 הליכה בדירה
          </button>
        )}
        {!walk && (<>
        <button
          className="btn !bg-white/90"
          onClick={() => {
            setTopDown(false)
            setFitKey((k) => k + 1)
          }}
        >
          ⟲ איפוס מבט
        </button>
        <button
          className="btn !bg-white/90"
          onClick={() => {
            setTopDown(true)
            setFitKey((k) => k + 1)
          }}
        >
          ⬒ מבט מלמעלה
        </button>
        </>)}
      </div>
      {walk && !locked && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-slate-900/25" data-testid="walk-hint">
          <div className="rounded-xl bg-white/95 px-6 py-4 text-center shadow-xl">
            <div className="text-lg font-bold text-slate-800">לחצו על המסך כדי להתחיל ללכת</div>
            <div className="mt-1 text-sm text-slate-600">W A S D / חצים — תנועה · עכבר — הסתכלות · Shift — ריצה · Esc — שחרור העכבר</div>
          </div>
        </div>
      )}
      {walk && locked && <div className="pointer-events-none absolute left-1/2 top-1/2 h-1.5 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white/80 ring-1 ring-slate-700/60" />}
      <div className="pointer-events-none absolute bottom-2 end-2 rounded bg-white/85 px-2 py-0.5 text-[11px] text-slate-500 shadow-sm">
        גרירה: סיבוב · גלגלת: זום · קליק ימני: הזזה · דאבל-קליק על הרצפה: הליכה משם · Alt: ללא הצמדה
      </div>
    </div>
  )
}
