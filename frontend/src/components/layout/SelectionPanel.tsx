import { useMemo } from 'react'
import { useFloor } from '../../hooks/useFloor'
import { useAppStore } from '../../store/useAppStore'
import { computeClearances, wallLength } from '../../utils/geometry'
import { formatCm, formatDims, formatIls } from '../../utils/format'
import { FLOOR_MATERIALS, swatchUrl } from '../../utils/floorMaterials'
import { ROOM_KINDS, ROOM_KIND_ORDER } from '../../utils/roomKinds'
import type { RoomKind } from '../../types'
import { parseRoomKey, roomAt } from '../../utils/rooms'

const SIDE_LABELS = { front: 'קדמי', back: 'אחורי', left: 'שמאל', right: 'ימין' } as const

function Num({
  label,
  value,
  onChange,
  min,
  max,
  step = 1,
  testId,
}: {
  label: string
  value: number
  onChange: (v: number) => void
  min?: number
  max?: number
  step?: number
  testId?: string
}) {
  return (
    <div>
      <label className="label">{label}</label>
      <input
        className="field ltr !w-[78px] !py-1"
        type="number"
        min={min}
        max={max}
        step={step}
        value={Number.isFinite(value) ? Number(value.toFixed(1)) : 0}
        data-testid={testId}
        onChange={(e) => {
          const v = Number(e.target.value)
          if (Number.isFinite(v)) onChange(v)
        }}
      />
    </div>
  )
}

export function SelectionPanel() {
  const selected = useAppStore((s) => s.selected)
  const walls = useAppStore((s) => s.walls)
  const openings = useAppStore((s) => s.openings)
  const items = useAppStore((s) => s.placedItems)
  const roomStyles = useAppStore((s) => s.roomStyles)
  const floor = useFloor()
  const st = useAppStore.getState

  const item = selected?.type === 'item' ? items.find((i) => i.id === selected.id) : undefined
  const wall = selected?.type === 'wall' ? walls.find((w) => w.id === selected.id) : undefined
  const opening = selected?.type === 'opening' ? openings.find((o) => o.id === selected.id) : undefined
  const clearances = useMemo(
    () => (item ? computeClearances(item, { walls, placedItems: items }) : []),
    [item, walls, items],
  )

  const resolvedRoom = (() => {
    if (!floor || selected?.type !== 'room') return undefined
    const p = parseRoomKey(selected.id)
    return floor.rooms[roomAt(floor.layout, p.x, p.y)]
  })()

  if (!item && !wall && !opening && !resolvedRoom) return null

  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-3 z-20 flex justify-center px-2">
    <div
      className="pointer-events-auto max-w-full rounded-xl border border-slate-200 bg-white/95 p-3 shadow-xl backdrop-blur"
      data-testid="selection-panel"
    >
      {item && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-baseline gap-x-3">
            <span className="text-sm font-bold text-slate-800">{item.title}</span>
            <span className="ltr text-xs text-slate-500">{formatDims(item.widthCm, item.depthCm, item.heightCm)}</span>
            <span className="text-xs font-semibold text-brand-700">{formatIls(item.priceIls)}</span>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <button className="btn" onClick={() => st().rotateItem90(item.id)} data-testid="rotate90">
              ⟳ 90°
            </button>
            <div>
              <label className="label">זווית חופשית: {Math.round(item.rotationDeg)}°</label>
              <input
                type="range"
                min={0}
                max={359}
                value={Math.round(item.rotationDeg)}
                className="w-32"
                onChange={(e) => st().updateItem(item.id, { rotationDeg: Number(e.target.value) }, `rot:${item.id}`)}
                data-testid="angle-slider"
              />
            </div>
            <Num label='X (ס"מ)' value={item.xCm} onChange={(v) => st().updateItem(item.id, { xCm: v }, `x:${item.id}`)} />
            <Num label='Z (ס"מ)' value={item.zCm} onChange={(v) => st().updateItem(item.id, { zCm: v }, `z:${item.id}`)} />
            <button className="btn" onClick={() => st().duplicateItem(item.id)} data-testid="duplicate">
              ⧉ שכפל
            </button>
            <button className="btn btn-danger" onClick={() => st().removeItem(item.id)} data-testid="delete-item">
              🗑 מחק
            </button>
          </div>
          {clearances.length > 0 && (
            <div className="flex flex-wrap gap-1.5 text-[11px]" data-testid="clearances">
              <span className="font-semibold text-slate-500">מרווחים:</span>
              {clearances.map((c) => (
                <span key={c.side} className="rounded bg-orange-50 px-1.5 py-0.5 font-medium text-orange-700">
                  {SIDE_LABELS[c.side]} {formatCm(c.cm, 0)} ס"מ ({c.target === 'wall' ? 'קיר' : 'פריט'})
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {resolvedRoom && floor && (
        <div className="space-y-2" data-testid="room-panel">
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label className="label">שם החדר</label>
              <input
                className="field !w-40 !py-1"
                value={roomStyles[resolvedRoom.styleIndex]?.name ?? resolvedRoom.name}
                onChange={(e) =>
                  st().upsertRoomStyle(
                    resolvedRoom.styleIndex,
                    { x: resolvedRoom.room.rep.x, y: resolvedRoom.room.rep.y, material: resolvedRoom.material, name: e.target.value, kind: resolvedRoom.kind },
                    `roomname:${resolvedRoom.room.id}`,
                  )
                }
                data-testid="room-name"
              />
            </div>
            <div>
              <label className="label">סוג החדר</label>
              <select
                className="field !w-36 !py-1"
                value={resolvedRoom.kind ?? 'room'}
                data-testid="room-kind"
                onChange={(e) => {
                  const kind = e.target.value as RoomKind
                  // changing the type also suggests that type's name and floor (both stay editable)
                  st().upsertRoomStyle(
                    resolvedRoom.styleIndex,
                    { x: resolvedRoom.room.rep.x, y: resolvedRoom.room.rep.y, kind, material: ROOM_KINDS[kind].material, name: ROOM_KINDS[kind].label },
                    `roomkind:${resolvedRoom.room.id}`,
                  )
                }}
              >
                {ROOM_KIND_ORDER.map((k) => (
                  <option key={k} value={k}>
                    {ROOM_KINDS[k].label}
                  </option>
                ))}
              </select>
            </div>
            <div className="pb-1 text-sm font-semibold text-slate-700">{resolvedRoom.areaM2.toFixed(1)} מ"ר</div>
            <button
              className="btn"
              onClick={() =>
                st().setAllRoomMaterials(
                  floor.rooms.map((r) => ({
                    x: r.room.rep.x,
                    y: r.room.rep.y,
                    name: r.styleIndex >= 0 ? roomStyles[r.styleIndex]?.name : undefined,
                  })),
                  resolvedRoom.material,
                )
              }
              title="החל את סוג הרצפה על כל החדרים"
            >
              החל על כל החדרים
            </button>
          </div>
          <div>
            <div className="label">רצפה</div>
            <div className="flex flex-wrap gap-2">
              {FLOOR_MATERIALS.map((m) => (
                <button
                  key={m.id}
                  onClick={() =>
                    st().upsertRoomStyle(
                      resolvedRoom.styleIndex,
                      {
                        x: resolvedRoom.room.rep.x,
                        y: resolvedRoom.room.rep.y,
                        material: m.id,
                        name: roomStyles[resolvedRoom.styleIndex]?.name,
                        kind: resolvedRoom.kind,
                      },
                      `roommat:${resolvedRoom.room.id}`,
                    )
                  }
                  className={`flex w-[74px] flex-col items-center gap-1 rounded-lg border p-1 text-[11px] ${
                    resolvedRoom.material === m.id ? 'border-brand-600 bg-brand-50 font-bold text-brand-700' : 'border-slate-200 hover:bg-slate-50'
                  }`}
                  data-testid={`floor-${m.id}`}
                >
                  <img src={swatchUrl(m.id)} alt="" className="h-10 w-10 rounded object-cover" />
                  {m.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {wall && (
        <div className="flex flex-wrap items-end gap-2">
          <span className="pb-1 text-sm font-bold text-slate-800">קיר · {formatCm(wallLength(wall), 0)} ס"מ</span>
          <Num
            label='עובי (ס"מ)'
            value={wall.thicknessCm}
            min={5}
            max={80}
            onChange={(v) => st().updateWall(wall.id, { thicknessCm: Math.max(5, v) })}
            testId="wall-thickness"
          />
          <button className="btn btn-danger" onClick={() => st().removeWall(wall.id)}>
            🗑 מחק קיר
          </button>
        </div>
      )}

      {opening && (
        <div className="flex flex-wrap items-end gap-2">
          <span className="pb-1 text-sm font-bold text-slate-800">{opening.kind === 'door' ? '🚪 דלת' : '🪟 חלון'}</span>
          <Num label='רוחב (ס"מ)' value={opening.widthCm} min={20} onChange={(v) => st().updateOpening(opening.id, { widthCm: Math.max(20, v) })} testId="opening-width" />
          <Num label='גובה (ס"מ)' value={opening.heightCm} min={20} onChange={(v) => st().updateOpening(opening.id, { heightCm: Math.max(20, v) })} testId="opening-height" />
          <Num label='סף תחתון (ס"מ)' value={opening.sillCm} min={0} onChange={(v) => st().updateOpening(opening.id, { sillCm: Math.max(0, v) })} testId="opening-sill" />
          <Num label='מיקום לאורך הקיר' value={opening.offsetCm} min={0} onChange={(v) => st().updateOpening(opening.id, { offsetCm: Math.max(0, v) })} />
          <div className="flex gap-1 pb-0.5">
            {[0, 30, 110].map((s) => (
              <button key={s} className={`chip ${opening.sillCm === s ? 'chip-active' : ''}`} onClick={() => st().updateOpening(opening.id, { sillCm: s })}>
                סף {s}
              </button>
            ))}
          </div>
          <button className="btn btn-danger" onClick={() => st().removeOpening(opening.id)}>
            🗑 מחק
          </button>
        </div>
      )}
    </div>
    </div>
  )
}
