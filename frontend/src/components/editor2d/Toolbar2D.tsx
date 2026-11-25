import { useState } from 'react'
import { useAppStore } from '../../store/useAppStore'
import type { Tool } from '../../types'
import { autoDetectWalls } from '../../utils/autoDetect'
import { furnishApartment } from '../../utils/furnishApartment'

const TOOLS: { id: Tool; label: string; icon: string; hint: string }[] = [
  { id: 'select', label: 'בחירה', icon: '↖', hint: 'בחירה והזזה' },
  { id: 'calibrate', label: 'כיול קנה מידה', icon: '📐', hint: 'לחצו על שתי נקודות וציינו אורך ידוע' },
  { id: 'wall', label: 'קירות', icon: '▭', hint: 'לחיצה לציור קיר · Enter/Esc/דאבל-קליק לסיום' },
  { id: 'opening', label: 'פתחים', icon: '🚪', hint: 'לחצו על קיר להוספת דלת/חלון' },
  { id: 'ruler', label: 'סרגל', icon: '📏', hint: 'מדידת מרחק חופשי בס"מ' },
]

export function Toolbar2D({ onFit }: { onFit: () => void }) {
  const tool = useAppStore((s) => s.tool)
  const setTool = useAppStore((s) => s.setTool)
  const openingKind = useAppStore((s) => s.openingKind)
  const setOpeningKind = useAppStore((s) => s.setOpeningKind)
  const ortho = useAppStore((s) => s.orthoSnap)
  const setOrtho = useAppStore((s) => s.setOrthoSnap)
  const grid = useAppStore((s) => s.gridSnap)
  const setGrid = useAppStore((s) => s.setGridSnap)
  const autoFurnish = useAppStore((s) => s.autoFurnish)
  const setAutoFurnish = useAppStore((s) => s.setAutoFurnish)
  const showFloors = useAppStore((s) => s.showFloors)
  const setShowFloors = useAppStore((s) => s.setShowFloors)
  const thickness = useAppStore((s) => s.newWallThicknessCm)
  const setThickness = useAppStore((s) => s.setNewWallThickness)
  const ceiling = useAppStore((s) => s.ceilingHeightCm)
  const setCeiling = useAppStore((s) => s.setCeilingHeight)

  const floorplanUrl = useAppStore((s) => s.floorplanUrl)
  const opacity = useAppStore((s) => s.floorplanOpacity)
  const setOpacity = useAppStore((s) => s.setFloorplanOpacity)
  const locked = useAppStore((s) => s.floorplanLocked)
  const setLocked = useAppStore((s) => s.setFloorplanLocked)
  const visible = useAppStore((s) => s.floorplanVisible)
  const setVisible = useAppStore((s) => s.setFloorplanVisible)
  const toast = useAppStore((s) => s.toast)
  const [detecting, setDetecting] = useState(false)

  const detectWalls = async () => {
    const st = useAppStore.getState()
    if (!st.floorplanUrl) return
    if (st.walls.length > 0 && !window.confirm('הקירות הקיימים יוחלפו בקירות שיזוהו מהתוכנית. להמשיך? (ניתן לבטל עם בטל)')) return
    setDetecting(true)
    try {
      await autoDetectWalls(st.pixelsPerCm)
    } finally {
      setDetecting(false)
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-slate-200 bg-white px-2 py-1.5 text-xs" data-testid="toolbar2d">
      <div className="flex gap-1">
        {TOOLS.map((t) => (
          <button
            key={t.id}
            title={t.hint}
            className={`btn ${tool === t.id ? 'btn-active' : ''}`}
            data-testid={`tool-${t.id}`}
            onClick={() => {
              if (t.id === 'calibrate' && !floorplanUrl) {
                toast('העלו תוכנית קומה כדי לכייל קנה מידה', 'info')
                return
              }
              setTool(t.id)
            }}
          >
            <span>{t.icon}</span>
            <span>{t.label}</span>
          </button>
        ))}
      </div>

      {tool === 'wall' && (
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1">
            עובי קיר
            <input
              className="field ltr !w-16 !py-0.5"
              type="number"
              min={5}
              max={60}
              value={thickness}
              onChange={(e) => setThickness(Math.max(5, Number(e.target.value) || 15))}
            />
            ס"מ
          </label>
          <label className="flex items-center gap-1">
            <input type="checkbox" checked={ortho} onChange={(e) => setOrtho(e.target.checked)} /> זווית ישרה 90°
          </label>
        </div>
      )}

      {tool === 'opening' && (
        <div className="flex gap-1">
          <button className={`btn ${openingKind === 'door' ? 'btn-active' : ''}`} onClick={() => setOpeningKind('door')}>
            🚪 דלת
          </button>
          <button className={`btn ${openingKind === 'window' ? 'btn-active' : ''}`} onClick={() => setOpeningKind('window')}>
            🪟 חלון
          </button>
        </div>
      )}

      <label className="flex items-center gap-1">
        <input type="checkbox" checked={grid} onChange={(e) => setGrid(e.target.checked)} /> הצמדה לרשת (5 ס"מ)
      </label>

      <label className="flex items-center gap-1" title="לאחר זיהוי הקירות, רהט את חדרי השינה והסלון מהקטלוג">
        <input type="checkbox" checked={autoFurnish} onChange={(e) => setAutoFurnish(e.target.checked)} /> ריהוט אוטומטי
      </label>

      <button
        className="btn"
        data-testid="furnish-now"
        onClick={async () => {
          const st = useAppStore.getState()
          if (st.placedItems.length > 0 && !window.confirm('להחליף את כל הריהוט בריהוט אוטומטי? (ניתן לבטל עם בטל)')) return
          const n = await furnishApartment({ replace: true })
          if (n) st.toast(`רוהטו ${n} פריטים`, 'success')
        }}
        title="רהט את החדרים מהקטלוג"
      >
        🛋 רהט
      </button>

      <label className="flex items-center gap-1">
        <input type="checkbox" checked={showFloors} onChange={(e) => setShowFloors(e.target.checked)} /> רצפות וחדרים
      </label>

      <label className="flex items-center gap-1">
        גובה תקרה
        <input
          className="field ltr !w-16 !py-0.5"
          type="number"
          min={200}
          max={500}
          value={ceiling}
          onChange={(e) => setCeiling(Number(e.target.value))}
        />
        ס"מ
      </label>

      {floorplanUrl && (
        <button
          className="btn border-brand-600 bg-brand-50 text-brand-700"
          onClick={detectWalls}
          disabled={detecting}
          title="זיהוי אוטומטי של קירות, דלתות וחלונות מהתוכנית"
          data-testid="detect-walls"
        >
          🪄 {detecting ? 'מזהה…' : 'זיהוי קירות אוטומטי'}
        </button>
      )}

      <button className="btn" onClick={onFit} title="התאם תצוגה">
        ⤢ התאם
      </button>

      {floorplanUrl && (
        <div className="flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5">
          <span className="font-medium">תוכנית:</span>
          <input
            type="range"
            min={0.05}
            max={1}
            step={0.05}
            value={opacity}
            onChange={(e) => setOpacity(Number(e.target.value))}
            className="w-20"
            title="שקיפות"
            data-testid="floorplan-opacity"
          />
          <button className={`btn !px-1.5 !py-0 ${locked ? 'btn-active' : ''}`} onClick={() => setLocked(!locked)} title="נעילה">
            {locked ? '🔒' : '🔓'}
          </button>
          <button className={`btn !px-1.5 !py-0 ${!visible ? 'btn-active' : ''}`} onClick={() => setVisible(!visible)} title="הצגה/הסתרה">
            {visible ? '👁' : '🚫'}
          </button>
        </div>
      )}
    </div>
  )
}
