import { useRef, useState } from 'react'
import { api } from '../../api/client'
import { selectBudgetTotal, useAppStore } from '../../store/useAppStore'
import type { ViewMode } from '../../types'
import { autoDetectWalls } from '../../utils/autoDetect'
import { formatIls } from '../../utils/format'
import { LoadProjectModal } from './ProjectModals'

const VIEW_MODES: { id: ViewMode; label: string }[] = [
  { id: '2d', label: 'דו-ממד 2D' },
  { id: 'split', label: 'מפוצל Split' },
  { id: '3d', label: 'תלת-ממד 3D' },
]

export function TopBar() {
  const name = useAppStore((s) => s.projectName)
  const setName = useAppStore((s) => s.setProjectName)
  const viewMode = useAppStore((s) => s.viewMode)
  const setViewMode = useAppStore((s) => s.setViewMode)
  const canUndo = useAppStore((s) => s.past.length > 0)
  const canRedo = useAppStore((s) => s.future.length > 0)
  const total = useAppStore(selectBudgetTotal)
  const toast = useAppStore((s) => s.toast)
  const fileRef = useRef<HTMLInputElement>(null)
  const [showLoad, setShowLoad] = useState(false)
  const [saving, setSaving] = useState(false)
  const [uploading, setUploading] = useState(false)

  const save = async () => {
    const s = useAppStore.getState()
    const body = {
      name: s.projectName.trim() || 'פרויקט ללא שם',
      floorplan_image_url: s.floorplanUrl,
      pixels_per_cm: s.pixelsPerCm,
      scene: {
        ceilingHeightCm: s.ceilingHeightCm,
        walls: s.walls,
        openings: s.openings,
        placedItems: s.placedItems,
        roomStyles: s.roomStyles,
      },
    }
    setSaving(true)
    try {
      const p = s.projectId ? await api.updateProject(s.projectId, body) : await api.createProject(body)
      s.setProjectId(p.id)
      toast('הפרויקט נשמר', 'success')
    } catch (e) {
      toast(e instanceof Error ? e.message : 'שגיאה בשמירה', 'error')
    } finally {
      setSaving(false)
    }
  }

  const newProject = () => {
    const s = useAppStore.getState()
    const dirty = s.walls.length + s.placedItems.length + s.openings.length > 0
    if (dirty && !window.confirm('להתחיל פרויקט חדש? שינויים שלא נשמרו יאבדו.')) return
    s.resetProject()
  }

  const onFile = async (file: File | undefined) => {
    if (!file) return
    if (useAppStore.getState().floorplanLocked && useAppStore.getState().floorplanUrl) {
      toast('התוכנית נעולה — בטלו נעילה כדי להחליף', 'info')
      return
    }
    setUploading(true)
    try {
      const r = await api.uploadFloorplan(file)
      const s = useAppStore.getState()
      const hadWalls = s.walls.length > 0
      s.setFloorplan(r.url, r.width_px > 0 ? { w: r.width_px, h: r.height_px } : null)
      s.setPixelsPerCm(null)
      if (hadWalls && !window.confirm('זוהו קירות מהתוכנית החדשה — להחליף את הקירות הקיימים? (ניתן לבטל עם בטל)')) {
        s.setTool('calibrate')
        toast('התוכנית הועלתה — כיילו קנה מידה או לחצו "זיהוי קירות אוטומטי"', 'info')
        return
      }
      toast('התוכנית הועלתה — מזהה קירות אוטומטית…', 'info')
      setUploading(true)
      await autoDetectWalls(null)
    } catch (e) {
      toast(e instanceof Error ? e.message : 'שגיאה בהעלאה', 'error')
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <header className="flex flex-wrap items-center gap-2 border-b border-slate-200 bg-white px-3 py-2 shadow-sm" data-testid="topbar">
      <div className="flex items-center gap-2">
        <span className="text-lg font-extrabold tracking-tight text-brand-700">🏠 RoomCraft 3D</span>
        <input
          className="field !w-48 font-semibold"
          value={name}
          onChange={(e) => setName(e.target.value)}
          aria-label="שם הפרויקט"
          data-testid="project-name"
        />
      </div>

      <div className="flex gap-1">
        <button className="btn" onClick={newProject}>
          ✚ חדש
        </button>
        <button className="btn" onClick={save} disabled={saving} data-testid="save-project">
          💾 {saving ? 'שומר…' : 'שמור'}
        </button>
        <button className="btn" onClick={() => setShowLoad(true)} data-testid="load-project">
          📂 פתח
        </button>
        <button className="btn" onClick={() => fileRef.current?.click()} disabled={uploading} data-testid="upload-floorplan">
          🗺 {uploading ? 'מעבד…' : 'העלאת תוכנית'}
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="image/png,image/jpeg,image/webp,application/pdf,.pdf"
          className="hidden"
          onChange={(e) => onFile(e.target.files?.[0])}
          data-testid="floorplan-input"
        />
      </div>

      <div className="mx-auto flex overflow-hidden rounded-lg border border-slate-300" role="tablist">
        {VIEW_MODES.map((m) => (
          <button
            key={m.id}
            role="tab"
            aria-selected={viewMode === m.id}
            onClick={() => setViewMode(m.id)}
            className={`px-3 py-1.5 text-sm font-medium transition ${
              viewMode === m.id ? 'bg-brand-600 text-white' : 'bg-white text-slate-600 hover:bg-slate-50'
            }`}
            data-testid={`view-${m.id}`}
          >
            {m.label}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-2">
        <button className="btn" disabled={!canUndo} onClick={() => useAppStore.getState().undo()} title="בטל (Ctrl+Z)" data-testid="undo">
          ↶ בטל
        </button>
        <button className="btn" disabled={!canRedo} onClick={() => useAppStore.getState().redo()} title="בצע שוב (Ctrl+Y)" data-testid="redo">
          ↷ חזור
        </button>
        <div className="rounded-lg bg-emerald-50 px-3 py-1 text-emerald-800" title="תקציב כולל של הפריטים בדירה">
          <span className="text-[11px] font-medium">תקציב: </span>
          <span className="text-base font-extrabold" data-testid="budget-badge">
            {formatIls(total)}
          </span>
        </div>
      </div>

      {showLoad && <LoadProjectModal onClose={() => setShowLoad(false)} />}
    </header>
  )
}
