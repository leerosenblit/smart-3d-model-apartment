import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { OPENING_DEFAULTS, useAppStore } from '../../store/useAppStore'
import type { PlacedItem, Point } from '../../types'
import { isProductDrag, resolveDroppedProduct } from '../../utils/dropProduct'
import { formatCm } from '../../utils/format'
import {
  clamp,
  computeClearances,
  dist,
  itemCorners,
  nearestWall,
  orthoSnap,
  roundTo,
  sceneBounds,
  snapItemToWalls,
  snapToEndpoints,
  wallAngle,
  wallCorners,
  wallDir,
  wallLength,
} from '../../utils/geometry'
import { CATEGORY_COLORS } from '../../utils/labels'
import { viewRegistry } from '../../utils/viewRegistry'
import { useFloor } from '../../hooks/useFloor'
import { placeProduct } from '../../hooks/useModelGeneration'
import { roomHighlightUrl } from '../../utils/floorTexture'
import { parseRoomKey, roomAt, roomKey } from '../../utils/rooms'
import { autoDetectWalls } from '../../utils/autoDetect'
import { Toolbar2D } from './Toolbar2D'

const GRID_STEP = 5
const BRAND = '#2f7de1'

interface View {
  x: number // plan cm at the left edge
  y: number // plan cm at the top edge
  k: number // screen px per cm
}

type DragState =
  | { kind: 'item'; id: string; offX: number; offY: number }
  | { kind: 'rotate'; id: string }
  | { kind: 'pan'; startX: number; startY: number; view: View; moved: boolean }
  | null

const isTyping = (t: EventTarget | null): boolean =>
  t instanceof HTMLElement && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT')

export function Editor2D() {
  const wrapRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const [size, setSize] = useState({ w: 800, h: 600 })
  const [view, setView] = useState<View>({ x: -100, y: -100, k: 0.5 })
  const viewRef = useRef(view)
  viewRef.current = view
  const fitted = useRef(false)

  const walls = useAppStore((s) => s.walls)
  const openings = useAppStore((s) => s.openings)
  const placedItems = useAppStore((s) => s.placedItems)
  const selected = useAppStore((s) => s.selected)
  const tool = useAppStore((s) => s.tool)
  const modelStates = useAppStore((s) => s.modelStates)
  const floorplanUrl = useAppStore((s) => s.floorplanUrl)
  const floorplanSize = useAppStore((s) => s.floorplanSize)
  const floorplanOpacity = useAppStore((s) => s.floorplanOpacity)
  const floorplanVisible = useAppStore((s) => s.floorplanVisible)
  const floorplanLocked = useAppStore((s) => s.floorplanLocked)
  const pixelsPerCm = useAppStore((s) => s.pixelsPerCm)
  const scaleEstimated = useAppStore((s) => s.scaleEstimated)
  const openingKind = useAppStore((s) => s.openingKind)
  const thickness = useAppStore((s) => s.newWallThicknessCm)
  const ortho = useAppStore((s) => s.orthoSnap)
  const gridSnap = useAppStore((s) => s.gridSnap)
  const showFloors = useAppStore((s) => s.showFloors)
  const floor = useFloor()

  const [chain, setChain] = useState<{ start: Point; last: Point; count: number } | null>(null)
  const [cursor, setCursor] = useState<Point | null>(null)
  const [ruler, setRuler] = useState<Point[]>([])
  const [calPts, setCalPts] = useState<Point[]>([])
  const [calValue, setCalValue] = useState('')
  const [hoverOpening, setHoverOpening] = useState<{ wallId: string; offsetCm: number; width: number } | null>(null)
  const [spaceDown, setSpaceDown] = useState(false)
  const [dropActive, setDropActive] = useState(false)
  const drag = useRef<DragState>(null)

  // effective pixels-per-cm for the floorplan image (unknown until calibrated → assume ~12 m wide)
  const effPpc = pixelsPerCm ?? (floorplanSize ? floorplanSize.w / 1200 : 1)
  const fpW = floorplanSize ? floorplanSize.w / effPpc : 0
  const fpH = floorplanSize ? floorplanSize.h / effPpc : 0

  // ---- sizing
  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    setSize({ w: el.clientWidth, h: el.clientHeight })
    return () => ro.disconnect()
  }, [])

  const toPlan = useCallback((clientX: number, clientY: number): Point => {
    const r = svgRef.current!.getBoundingClientRect()
    const v = viewRef.current
    return { x: v.x + (clientX - r.left) / v.k, y: v.y + (clientY - r.top) / v.k }
  }, [])

  const fit = useCallback(() => {
    const b = sceneBounds({ walls, placedItems })
    let { minX, minY, maxX, maxY } = b
    if (fpW) {
      minX = Math.min(minX, 0)
      minY = Math.min(minY, 0)
      maxX = Math.max(maxX, fpW)
      maxY = Math.max(maxY, fpH)
    }
    const pad = 80
    const w = Math.max(100, maxX - minX + pad * 2)
    const h = Math.max(100, maxY - minY + pad * 2)
    const k = clamp(Math.min(size.w / w, size.h / h), 0.05, 5)
    setView({ k, x: minX - pad - (size.w / k - w) / 2, y: minY - pad - (size.h / k - h) / 2 })
  }, [walls, placedItems, fpW, fpH, size.w, size.h])

  // initial fit (once real size is known), and again when a floorplan first appears
  useEffect(() => {
    if (size.w > 50 && !fitted.current) {
      fitted.current = true
      fit()
    }
  }, [size.w, fit])
  const lastFp = useRef<string | null>(null)
  useEffect(() => {
    if (floorplanUrl && floorplanSize && lastFp.current !== floorplanUrl) {
      lastFp.current = floorplanUrl
      fit()
    }
  }, [floorplanUrl, floorplanSize, fit])

  // expose view center to the sidebar "add" button
  useEffect(() => {
    viewRegistry.center2d = () => {
      const v = viewRef.current
      return { x: v.x + size.w / 2 / v.k, y: v.y + size.h / 2 / v.k }
    }
    return () => {
      viewRegistry.center2d = null
    }
  }, [size.w, size.h])

  // ---- wheel zoom (non-passive)
  useEffect(() => {
    const el = svgRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const v = viewRef.current
      const r = el.getBoundingClientRect()
      const mx = e.clientX - r.left
      const my = e.clientY - r.top
      const k = clamp(v.k * Math.pow(1.0015, -e.deltaY), 0.05, 6)
      const px = v.x + mx / v.k
      const py = v.y + my / v.k
      setView({ k, x: px - mx / k, y: py - my / k })
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  // ---- keyboard: space = pan, Esc/Enter finish
  const finishChain = useCallback(() => setChain(null), [])
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (isTyping(e.target)) return
      if (e.code === 'Space') {
        setSpaceDown(true)
        e.preventDefault()
      } else if (e.key === 'Enter' || e.key === 'Escape') {
        finishChain()
        setRuler([])
        setCalPts([])
        setCalValue('')
        if (e.key === 'Escape') useAppStore.getState().setTool('select')
      }
    }
    const up = (e: KeyboardEvent) => {
      if (e.code === 'Space') setSpaceDown(false)
    }
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
    }
  }, [finishChain])

  useEffect(() => {
    if (tool !== 'wall') setChain(null)
    if (tool !== 'ruler') setRuler([])
    if (tool !== 'calibrate') {
      setCalPts([])
      setCalValue('')
    }
    if (tool !== 'opening') setHoverOpening(null)
  }, [tool])

  // ---- snapping
  const snapPlan = useCallback(
    (p: Point, opts: { from?: Point; endpoints?: boolean; free?: boolean } = {}): Point => {
      if (opts.free) return p
      const thr = 12 / viewRef.current.k
      if (opts.endpoints) {
        const e = snapToEndpoints(p, walls, thr)
        if (e) return e
      }
      let q = p
      if (opts.from && ortho) q = orthoSnap(opts.from, q)
      if (gridSnap) {
        q = { x: opts.from && ortho && q.x === opts.from.x ? q.x : roundTo(q.x, GRID_STEP), y: opts.from && ortho && q.y === opts.from.y ? q.y : roundTo(q.y, GRID_STEP) }
      }
      return q
    },
    [walls, ortho, gridSnap],
  )

  // ---- pointer handling
  const onPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    const svg = svgRef.current!
    const raw = toPlan(e.clientX, e.clientY)
    const startPan = () => {
      drag.current = { kind: 'pan', startX: e.clientX, startY: e.clientY, view: viewRef.current, moved: false }
      svg.setPointerCapture(e.pointerId)
    }
    if (e.button === 1 || (e.button === 0 && spaceDown)) {
      e.preventDefault()
      startPan()
      return
    }
    if (e.button === 2) {
      if (tool === 'wall') finishChain()
      return
    }
    if (e.button !== 0) return

    switch (tool) {
      case 'select':
        startPan() // click without moving → deselect (see pointerup)
        break
      case 'wall': {
        const p = snapPlan(raw, { from: chain?.last, endpoints: true })
        const st = useAppStore.getState()
        if (!chain) {
          setChain({ start: p, last: p, count: 0 })
        } else if (dist(p, chain.last) >= 1) {
          st.addWalls([{ x1: chain.last.x, y1: chain.last.y, x2: p.x, y2: p.y, thicknessCm: thickness }])
          if (chain.count >= 1 && dist(p, chain.start) < 1) setChain(null) // closed loop
          else setChain({ ...chain, last: p, count: chain.count + 1 })
        }
        break
      }
      case 'opening': {
        const hit = nearestWall(raw, walls, 30 / viewRef.current.k)
        if (hit) {
          const def = OPENING_DEFAULTS[openingKind]
          const len = wallLength(hit.wall)
          const width = Math.min(def.widthCm, Math.max(20, len - 2))
          const offset = clamp(roundTo(hit.offsetCm, gridSnap ? GRID_STEP : 1), width / 2, len - width / 2)
          const id = useAppStore.getState().addOpening({
            wallId: hit.wall.id,
            kind: openingKind,
            offsetCm: offset,
            widthCm: width,
            heightCm: def.heightCm,
            sillCm: def.sillCm,
          })
          useAppStore.getState().setSelected({ type: 'opening', id })
        } else {
          useAppStore.getState().toast('לחצו על קיר כדי להוסיף פתח', 'info')
        }
        break
      }
      case 'ruler': {
        const p = snapPlan(raw, { endpoints: true })
        const corners = [...placedItems.flatMap(itemCorners), ...walls.flatMap(wallCorners)]
        let best = p
        let bd = 12 / viewRef.current.k
        for (const c of corners) {
          const d = dist(c, raw)
          if (d < bd) {
            bd = d
            best = c
          }
        }
        setRuler((r) => (r.length >= 2 ? [best] : [...r, best]))
        break
      }
      case 'calibrate': {
        if (floorplanLocked) {
          useAppStore.getState().toast('התוכנית נעולה — בטלו נעילה כדי לכייל', 'info')
          break
        }
        if (calPts.length < 2) setCalPts((c) => [...c, raw])
        break
      }
    }
  }

  const onPointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const raw = toPlan(e.clientX, e.clientY)
    const d = drag.current
    const st = useAppStore.getState()
    if (d?.kind === 'pan') {
      const dx = e.clientX - d.startX
      const dy = e.clientY - d.startY
      if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true
      if (d.moved) setView({ k: d.view.k, x: d.view.x - dx / d.view.k, y: d.view.y - dy / d.view.k })
      return
    }
    if (d?.kind === 'item') {
      const it = st.placedItems.find((i) => i.id === d.id)
      if (!it) return
      let p = { x: raw.x - d.offX, y: raw.y - d.offY }
      if (!e.altKey) {
        if (st.gridSnap) p = { x: roundTo(p.x, GRID_STEP), y: roundTo(p.y, GRID_STEP) }
        p = snapItemToWalls({ ...it, xCm: p.x, zCm: p.y }, st.walls, 8)
      }
      st.moveItemLive(d.id, Math.round(p.x * 10) / 10, Math.round(p.y * 10) / 10)
      return
    }
    if (d?.kind === 'rotate') {
      const it = st.placedItems.find((i) => i.id === d.id)
      if (!it) return
      let deg = (Math.atan2(raw.y - it.zCm, raw.x - it.xCm) * 180) / Math.PI + 90
      if (!e.shiftKey) deg = Math.round(deg / 5) * 5
      st.setItemRotationLive(d.id, deg)
      return
    }
    // hover feedback
    if (tool === 'wall') setCursor(snapPlan(raw, { from: chain?.last, endpoints: true }))
    else if (tool === 'ruler') setCursor(raw)
    else if (tool === 'opening') {
      const hit = nearestWall(raw, walls, 30 / viewRef.current.k)
      if (hit) {
        const def = OPENING_DEFAULTS[openingKind]
        const len = wallLength(hit.wall)
        const width = Math.min(def.widthCm, Math.max(20, len - 2))
        setHoverOpening({
          wallId: hit.wall.id,
          width,
          offsetCm: clamp(roundTo(hit.offsetCm, gridSnap ? GRID_STEP : 1), width / 2, len - width / 2),
        })
      } else setHoverOpening(null)
    } else if (tool === 'calibrate') setCursor(raw)
  }

  const onPointerUp = (e: React.PointerEvent<SVGSVGElement>) => {
    const d = drag.current
    drag.current = null
    try {
      svgRef.current?.releasePointerCapture(e.pointerId)
    } catch {
      /* not captured */
    }
    if (d?.kind === 'pan' && !d.moved && tool === 'select') {
      // click on empty canvas: pick the room under the cursor (if any), else deselect
      const p = toPlan(e.clientX, e.clientY)
      const room = floor ? floor.layout.rooms[roomAt(floor.layout, p.x, p.y)] : undefined
      useAppStore.getState().setSelected(room ? { type: 'room', id: roomKey(room) } : null)
    }
    if (tool === 'calibrate' && calPts.length === 2 && !calValue) setCalValue('')
  }

  const startItemDrag = (e: React.PointerEvent, it: PlacedItem) => {
    if (tool !== 'select' || e.button !== 0 || spaceDown) return
    e.stopPropagation()
    const raw = toPlan(e.clientX, e.clientY)
    const st = useAppStore.getState()
    st.setSelected({ type: 'item', id: it.id })
    st.pushHistory() // one undo entry per drag
    drag.current = { kind: 'item', id: it.id, offX: raw.x - it.xCm, offY: raw.y - it.zCm }
    svgRef.current!.setPointerCapture(e.pointerId)
  }

  const startRotate = (e: React.PointerEvent, it: PlacedItem) => {
    e.stopPropagation()
    useAppStore.getState().pushHistory()
    drag.current = { kind: 'rotate', id: it.id }
    svgRef.current!.setPointerCapture(e.pointerId)
  }

  // ---- drop from catalog
  const onDrop = async (e: React.DragEvent) => {
    e.preventDefault()
    setDropActive(false)
    const p = await resolveDroppedProduct(e.dataTransfer)
    if (!p) return
    const pt = toPlan(e.clientX, e.clientY)
    placeProduct(p, roundTo(pt.x, GRID_STEP), roundTo(pt.y, GRID_STEP))
  }

  // ---- calibration confirm
  const applyCalibration = () => {
    const known = Number(calValue)
    if (calPts.length !== 2 || !(known > 0)) return
    const planDist = dist(calPts[0], calPts[1])
    const pxDist = planDist * effPpc
    const wasEstimated = useAppStore.getState().scaleEstimated
    const newPpc = pxDist / known
    useAppStore.getState().setPixelsPerCm(newPpc)
    useAppStore.getState().toast(`קנה המידה כויל: ${formatCm(newPpc, 2)} פיקסלים לס"מ`, 'success')
    // walls that were auto-detected at the estimated scale must be re-derived at the exact one
    if (wasEstimated) void autoDetectWalls(newPpc)
    setCalPts([])
    setCalValue('')
    useAppStore.getState().setTool('select')
  }

  // ---- derived
  const k = view.k
  const sel = selected
  const floorUrl = useMemo(() => (floor ? floor.canvas.toDataURL('image/png') : null), [floor])
  const selRoomId = useMemo(() => {
    if (!floor || sel?.type !== 'room') return -1
    const p = parseRoomKey(sel.id)
    return roomAt(floor.layout, p.x, p.y)
  }, [floor, sel])
  const roomHighlight = useMemo(
    () => (floor && selRoomId >= 0 ? roomHighlightUrl(floor.layout, selRoomId) : null),
    [floor, selRoomId],
  )
  const selItem = sel?.type === 'item' ? placedItems.find((i) => i.id === sel.id) : undefined
  const clearances = useMemo(
    () => (selItem ? computeClearances(selItem, { walls, placedItems }) : []),
    [selItem, walls, placedItems],
  )
  const px = (v: number) => v / k // screen px → plan cm
  const interactive = tool === 'select'

  const cursorStyle =
    spaceDown || drag.current?.kind === 'pan' ? 'grabbing' : tool === 'select' ? 'default' : 'crosshair'

  const calPreview = calPts.length === 1 && cursor ? [calPts[0], cursor] : calPts

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="editor2d">
      <Toolbar2D onFit={fit} />
      <div
        ref={wrapRef}
        className={`relative min-h-0 flex-1 overflow-hidden bg-[#f8fafc] ${dropActive ? 'ring-4 ring-inset ring-brand-500/50' : ''}`}
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
        <svg
          ref={svgRef}
          width={size.w}
          height={size.h}
          style={{ direction: 'ltr', cursor: cursorStyle, touchAction: 'none', display: 'block' }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onDoubleClick={() => tool === 'wall' && finishChain()}
          onContextMenu={(e) => e.preventDefault()}
          data-testid="editor2d-svg"
        >
          <defs>
            <pattern id="grid-minor" width={50} height={50} patternUnits="userSpaceOnUse">
              <path d="M 50 0 L 0 0 0 50" fill="none" stroke="#e2e8f0" strokeWidth={1} vectorEffect="non-scaling-stroke" />
            </pattern>
            <pattern id="grid-major" width={100} height={100} patternUnits="userSpaceOnUse">
              <path d="M 100 0 L 0 0 0 100" fill="none" stroke="#cbd5e1" strokeWidth={1} vectorEffect="non-scaling-stroke" />
            </pattern>
          </defs>
          <g transform={`scale(${k}) translate(${-view.x} ${-view.y})`}>
            {/* grid */}
            {k > 0.12 && (
              <>
                <rect x={-20000} y={-20000} width={40000} height={40000} fill="url(#grid-minor)" pointerEvents="none" />
                <rect x={-20000} y={-20000} width={40000} height={40000} fill="url(#grid-major)" pointerEvents="none" />
              </>
            )}
            {/* origin marker */}
            <circle cx={0} cy={0} r={px(3)} fill="#94a3b8" pointerEvents="none" />

            {/* floorplan */}
            {floorplanUrl && floorplanVisible && fpW > 0 && (
              <image
                href={floorplanUrl}
                x={0}
                y={0}
                width={fpW}
                height={fpH}
                opacity={floorplanOpacity}
                preserveAspectRatio="none"
                pointerEvents="none"
              />
            )}

            {/* room floors (procedural wood / tile / ...) */}
            {floor && showFloors && floorUrl && (
              <image
                href={floorUrl}
                x={floor.originX}
                y={floor.originY}
                width={floor.widthCm}
                height={floor.heightCm}
                opacity={floorplanUrl && floorplanVisible ? 0.8 : 1}
                preserveAspectRatio="none"
                pointerEvents="none"
              />
            )}
            {floor && roomHighlight && (
              <image
                href={roomHighlight}
                x={floor.originX}
                y={floor.originY}
                width={floor.widthCm}
                height={floor.heightCm}
                preserveAspectRatio="none"
                pointerEvents="none"
              />
            )}

            {/* walls */}
            {walls.map((w) => {
              const isSel = sel?.type === 'wall' && sel.id === w.id
              const pts = wallCorners(w)
                .map((p) => `${p.x},${p.y}`)
                .join(' ')
              return (
                <polygon
                  key={w.id}
                  points={pts}
                  fill={isSel ? BRAND : '#475569'}
                  stroke={isSel ? '#1e3a8a' : '#1e293b'}
                  strokeWidth={1}
                  vectorEffect="non-scaling-stroke"
                  style={{ pointerEvents: interactive ? 'all' : 'none', cursor: 'pointer' }}
                  onPointerDown={(e) => {
                    if (!interactive || e.button !== 0 || spaceDown) return
                    e.stopPropagation()
                    useAppStore.getState().setSelected({ type: 'wall', id: w.id })
                  }}
                />
              )
            })}

            {/* openings */}
            {openings.map((o) => {
              const w = walls.find((x) => x.id === o.wallId)
              if (!w) return null
              const d = wallDir(w)
              const cx = w.x1 + d.x * o.offsetCm
              const cy = w.y1 + d.y * o.offsetCm
              const ang = (wallAngle(w) * 180) / Math.PI
              const t = w.thicknessCm
              const isSel = sel?.type === 'opening' && sel.id === o.id
              const isDoor = o.kind === 'door'
              const stroke = isSel ? BRAND : '#0f172a'
              return (
                <g
                  key={o.id}
                  transform={`translate(${cx} ${cy}) rotate(${ang})`}
                  style={{ pointerEvents: interactive ? 'all' : 'none', cursor: 'pointer' }}
                  onPointerDown={(e) => {
                    if (!interactive || e.button !== 0 || spaceDown) return
                    e.stopPropagation()
                    useAppStore.getState().setSelected({ type: 'opening', id: o.id })
                  }}
                >
                  <rect
                    x={-o.widthCm / 2}
                    y={-t / 2 - 0.5}
                    width={o.widthCm}
                    height={t + 1}
                    fill={isDoor ? '#f8fafc' : '#bae6fd'}
                    stroke={stroke}
                    strokeWidth={isSel ? 2 : 1}
                    vectorEffect="non-scaling-stroke"
                  />
                  {isDoor ? (
                    <>
                      <line x1={-o.widthCm / 2} y1={0} x2={-o.widthCm / 2} y2={o.widthCm} stroke={stroke} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
                      <path
                        d={`M ${-o.widthCm / 2} ${o.widthCm} A ${o.widthCm} ${o.widthCm} 0 0 0 ${o.widthCm / 2} 0`}
                        fill="none"
                        stroke={stroke}
                        strokeWidth={1}
                        strokeDasharray="4 3"
                        vectorEffect="non-scaling-stroke"
                      />
                    </>
                  ) : (
                    <>
                      <line x1={-o.widthCm / 2} y1={0} x2={o.widthCm / 2} y2={0} stroke={stroke} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
                    </>
                  )}
                </g>
              )
            })}

            {/* hover ghost for opening tool */}
            {tool === 'opening' && hoverOpening && (() => {
              const w = walls.find((x) => x.id === hoverOpening.wallId)
              if (!w) return null
              const d = wallDir(w)
              return (
                <g
                  transform={`translate(${w.x1 + d.x * hoverOpening.offsetCm} ${w.y1 + d.y * hoverOpening.offsetCm}) rotate(${(wallAngle(w) * 180) / Math.PI})`}
                  pointerEvents="none"
                >
                  <rect x={-hoverOpening.width / 2} y={-w.thicknessCm / 2 - 1} width={hoverOpening.width} height={w.thicknessCm + 2} fill={BRAND} opacity={0.4} />
                </g>
              )
            })()}

            {/* wall length labels */}
            {walls.map((w) => {
              const len = wallLength(w)
              if (len < 1) return null
              const mx = (w.x1 + w.x2) / 2
              const my = (w.y1 + w.y2) / 2
              const d = wallDir(w)
              const off = w.thicknessCm / 2 + px(11)
              let ang = (wallAngle(w) * 180) / Math.PI
              if (ang > 90 || ang < -90) ang += 180
              return (
                <text
                  key={`l-${w.id}`}
                  x={mx - d.y * off}
                  y={my + d.x * off}
                  transform={`rotate(${ang} ${mx - d.y * off} ${my + d.x * off})`}
                  fontSize={px(12)}
                  textAnchor="middle"
                  dominantBaseline="middle"
                  fill="#0f172a"
                  stroke="#f8fafc"
                  strokeWidth={px(3)}
                  paintOrder="stroke"
                  pointerEvents="none"
                  fontWeight={600}
                >
                  {formatCm(len, 0)} ס"מ
                </text>
              )
            })}

            {/* room names + areas */}
            {floor && showFloors &&
              floor.rooms.map((r) => {
                const inside = roomAt(floor.layout, r.room.cx, r.room.cy) === r.room.id
                const lx = inside ? r.room.cx : r.room.rep.x
                const ly = inside ? r.room.cy : r.room.rep.y
                return (
                  <g key={`room-${r.room.id}`} pointerEvents="none">
                    <text x={lx} y={ly - px(2)} fontSize={px(13)} fontWeight={700} textAnchor="middle" fill="#1e293b" stroke="#fff" strokeWidth={px(3.5)} paintOrder="stroke">
                      {r.name}
                    </text>
                    <text x={lx} y={ly + px(13)} fontSize={px(11)} textAnchor="middle" fill="#475569" stroke="#fff" strokeWidth={px(3)} paintOrder="stroke">
                      {r.areaM2.toFixed(1)} מ"ר
                    </text>
                  </g>
                )
              })}

            {/* placed items */}
            {placedItems.map((it) => {
              const isSel = sel?.type === 'item' && sel.id === it.id
              const color = CATEGORY_COLORS[it.category] ?? '#90a4ae'
              const ms = modelStates[it.productId]
              const generating = ms?.status === 'generating'
              const hw = it.widthCm / 2
              const hd = it.depthCm / 2
              const fs = clamp(Math.min(it.widthCm / 7, 13 / k), 5, 30)
              return (
                <g
                  key={it.id}
                  transform={`translate(${it.xCm} ${it.zCm}) rotate(${it.rotationDeg})`}
                  style={{ pointerEvents: interactive ? 'all' : 'none', cursor: interactive ? 'move' : 'default' }}
                  onPointerDown={(e) => startItemDrag(e, it)}
                  data-testid="item-2d"
                >
                  <rect
                    x={-hw}
                    y={-hd}
                    width={it.widthCm}
                    height={it.depthCm}
                    fill={color}
                    fillOpacity={0.45}
                    stroke={isSel ? BRAND : color}
                    strokeWidth={isSel ? 2.5 : 1.5}
                    strokeDasharray={generating ? '6 4' : undefined}
                    vectorEffect="non-scaling-stroke"
                  />
                  {/* front edge marker (local +z) */}
                  <line x1={-hw} y1={hd} x2={hw} y2={hd} stroke={isSel ? BRAND : '#1e293b'} strokeWidth={3} vectorEffect="non-scaling-stroke" opacity={0.7} />
                  <g transform={`rotate(${-it.rotationDeg})`} pointerEvents="none">
                    <text textAnchor="middle" y={-fs * 0.2} fontSize={fs} fontWeight={700} fill="#0f172a" stroke="#fff" strokeWidth={fs * 0.18} paintOrder="stroke">
                      {it.title.length > 22 ? `${it.title.slice(0, 21)}…` : it.title}
                    </text>
                    <text textAnchor="middle" y={fs * 1.05} fontSize={fs * 0.85} fill="#334155" stroke="#fff" strokeWidth={fs * 0.15} paintOrder="stroke">
                      {formatCm(it.widthCm, 0)}×{formatCm(it.depthCm, 0)} ס"מ
                    </text>
                  </g>
                  {isSel && (
                    <>
                      <line x1={0} y1={-hd} x2={0} y2={-hd - px(26)} stroke={BRAND} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
                      <circle
                        cx={0}
                        cy={-hd - px(26)}
                        r={px(7)}
                        fill="#fff"
                        stroke={BRAND}
                        strokeWidth={2}
                        vectorEffect="non-scaling-stroke"
                        style={{ cursor: 'grab' }}
                        onPointerDown={(e) => startRotate(e, it)}
                        data-testid="rotate-handle"
                      />
                    </>
                  )}
                </g>
              )
            })}

            {/* clearance lines */}
            {clearances.map((c) => (
              <g key={c.side} pointerEvents="none">
                <line x1={c.from.x} y1={c.from.y} x2={c.to.x} y2={c.to.y} stroke="#f97316" strokeWidth={1.5} strokeDasharray="5 3" vectorEffect="non-scaling-stroke" />
                <circle cx={c.to.x} cy={c.to.y} r={px(3)} fill="#f97316" />
                <text
                  x={(c.from.x + c.to.x) / 2}
                  y={(c.from.y + c.to.y) / 2 - px(4)}
                  fontSize={px(11)}
                  textAnchor="middle"
                  fill="#c2410c"
                  stroke="#fff"
                  strokeWidth={px(3)}
                  paintOrder="stroke"
                  fontWeight={700}
                >
                  {formatCm(c.cm, 0)}
                </text>
              </g>
            ))}

            {/* wall preview */}
            {tool === 'wall' && chain && cursor && (
              <g pointerEvents="none">
                <line x1={chain.last.x} y1={chain.last.y} x2={cursor.x} y2={cursor.y} stroke={BRAND} strokeWidth={thickness} strokeOpacity={0.35} strokeLinecap="butt" />
                <line x1={chain.last.x} y1={chain.last.y} x2={cursor.x} y2={cursor.y} stroke={BRAND} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
                <text
                  x={(chain.last.x + cursor.x) / 2}
                  y={(chain.last.y + cursor.y) / 2 - px(10)}
                  fontSize={px(12)}
                  textAnchor="middle"
                  fill={BRAND}
                  fontWeight={700}
                  stroke="#fff"
                  strokeWidth={px(3)}
                  paintOrder="stroke"
                >
                  {formatCm(dist(chain.last, cursor), 0)} ס"מ
                </text>
              </g>
            )}
            {tool === 'wall' && cursor && (
              <circle cx={cursor.x} cy={cursor.y} r={px(5)} fill="none" stroke={BRAND} strokeWidth={2} vectorEffect="non-scaling-stroke" pointerEvents="none" />
            )}

            {/* ruler */}
            {tool === 'ruler' && (ruler.length > 0) && (() => {
              const a = ruler[0]
              const b = ruler.length === 2 ? ruler[1] : cursor
              if (!b) return null
              return (
                <g pointerEvents="none">
                  <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#dc2626" strokeWidth={2} vectorEffect="non-scaling-stroke" />
                  <circle cx={a.x} cy={a.y} r={px(4)} fill="#dc2626" />
                  <circle cx={b.x} cy={b.y} r={px(4)} fill="#dc2626" />
                  <text
                    x={(a.x + b.x) / 2}
                    y={(a.y + b.y) / 2 - px(8)}
                    fontSize={px(14)}
                    textAnchor="middle"
                    fill="#b91c1c"
                    fontWeight={800}
                    stroke="#fff"
                    strokeWidth={px(4)}
                    paintOrder="stroke"
                  >
                    {formatCm(dist(a, b), 1)} ס"מ
                  </text>
                </g>
              )
            })()}

            {/* calibration */}
            {tool === 'calibrate' && calPreview.length > 0 && (
              <g pointerEvents="none">
                {calPreview.length === 2 && (
                  <line x1={calPreview[0].x} y1={calPreview[0].y} x2={calPreview[1].x} y2={calPreview[1].y} stroke="#9333ea" strokeWidth={2} vectorEffect="non-scaling-stroke" />
                )}
                {calPts.map((p, i) => (
                  <circle key={i} cx={p.x} cy={p.y} r={px(5)} fill="#9333ea" />
                ))}
              </g>
            )}
          </g>
        </svg>

        {/* hints */}
        <div className="pointer-events-none absolute start-2 top-2 rounded bg-white/85 px-2 py-1 text-[11px] text-slate-600 shadow-sm">
          {tool === 'wall' && (chain ? 'לחצו להמשך · Enter/דאבל-קליק/קליק ימני לסיום' : 'לחצו להתחלת קיר')}
          {tool === 'opening' && `לחצו על קיר להוספת ${openingKind === 'door' ? 'דלת' : 'חלון'}`}
          {tool === 'ruler' && 'לחצו על שתי נקודות למדידה'}
          {tool === 'calibrate' && (calPts.length < 2 ? `סמנו נקודה ${calPts.length + 1} מתוך 2 על התוכנית` : 'הזינו את האורך הידוע')}
          {tool === 'select' && 'גלגלת: זום · רווח/גלגלת-לחוצה: הזזה · Alt: ללא הצמדה'}
          {!floorplanUrl && walls.length === 0 && ' · העלו תוכנית קומה או התחילו לצייר קירות'}
        </div>
        <div className="pointer-events-none absolute bottom-2 end-2 rounded bg-white/85 px-2 py-0.5 text-[11px] text-slate-500 shadow-sm ltr">
          {Math.round(k * 100) / 100} px/cm
        </div>

        {/* calibration prompt */}
        {tool === 'calibrate' && calPts.length === 2 && (
          <div className="absolute left-1/2 top-4 z-10 w-max max-w-[96%] -translate-x-1/2 rounded-lg border border-purple-300 bg-white p-3 shadow-lg" data-testid="calibrate-prompt">
            <div className="mb-1 text-sm font-semibold text-slate-700">מה האורך האמיתי בין שתי הנקודות?</div>
            <div className="flex items-center gap-2">
              <input
                autoFocus
                className="field ltr !w-28"
                type="number"
                min={1}
                placeholder="418"
                value={calValue}
                onChange={(e) => setCalValue(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && applyCalibration()}
                data-testid="calibrate-input"
              />
              <span className="text-sm">ס"מ</span>
              <button className="btn btn-primary" disabled={!(Number(calValue) > 0)} onClick={applyCalibration} data-testid="calibrate-apply">
                כייל
              </button>
              <button
                className="btn"
                onClick={() => {
                  setCalPts([])
                  setCalValue('')
                }}
              >
                ביטול
              </button>
            </div>
          </div>
        )}
        {floorplanUrl && (pixelsPerCm === null || scaleEstimated) && tool !== 'calibrate' && (
          <button
            className="btn absolute bottom-2 start-2 border-amber-400 bg-amber-50 text-amber-800"
            onClick={() => useAppStore.getState().setTool('calibrate')}
          >
            ⚠ {scaleEstimated ? 'קנה המידה הוערך אוטומטית' : 'התוכנית טרם כוילה'} — לחצו לכיול מדויק
          </button>
        )}
      </div>
    </div>
  )
}
