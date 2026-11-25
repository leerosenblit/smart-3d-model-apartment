import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import { useAppStore } from '../../store/useAppStore'
import type { ProjectSummary } from '../../types'

export function LoadProjectModal({ onClose }: { onClose: () => void }) {
  const [list, setList] = useState<ProjectSummary[] | null>(null)
  const toast = useAppStore((s) => s.toast)
  const loadProject = useAppStore((s) => s.loadProject)

  const refresh = () =>
    api
      .listProjects()
      .then(setList)
      .catch((e) => {
        toast(e instanceof Error ? e.message : 'שגיאה', 'error')
        setList([])
      })

  useEffect(() => {
    void refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const open = async (id: number) => {
    try {
      const p = await api.getProject(id)
      loadProject(p)
      toast(`הפרויקט "${p.name}" נטען`, 'success')
      onClose()
    } catch (e) {
      toast(e instanceof Error ? e.message : 'שגיאה בטעינה', 'error')
    }
  }

  const remove = async (p: ProjectSummary) => {
    if (!window.confirm(`למחוק את "${p.name}"? לא ניתן לשחזר.`)) return
    try {
      await api.deleteProject(p.id)
      if (useAppStore.getState().projectId === p.id) useAppStore.getState().setProjectId(null)
      void refresh()
    } catch (e) {
      toast(e instanceof Error ? e.message : 'שגיאה במחיקה', 'error')
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40" onClick={onClose} data-testid="load-modal">
      <div className="w-[420px] max-w-[94vw] rounded-xl bg-white p-4 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-bold">פתיחת פרויקט</h2>
          <button className="btn !px-2 !py-0.5" onClick={onClose}>
            ✕
          </button>
        </div>
        {list === null && <p className="py-6 text-center text-sm text-slate-400">טוען…</p>}
        {list && list.length === 0 && <p className="py-6 text-center text-sm text-slate-400">אין פרויקטים שמורים</p>}
        <ul className="max-h-72 space-y-1.5 overflow-y-auto">
          {list?.map((p) => (
            <li key={p.id} className="flex items-center gap-2 rounded-lg border border-slate-200 p-2 hover:bg-slate-50">
              <button className="min-w-0 flex-1 text-start" onClick={() => open(p.id)}>
                <div className="truncate text-sm font-semibold">{p.name}</div>
                <div className="text-[11px] text-slate-500">{new Date(p.updated_at).toLocaleString('he-IL')}</div>
              </button>
              <button className="btn btn-danger !px-2 !py-0.5" onClick={() => remove(p)} title="מחק">
                🗑
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
