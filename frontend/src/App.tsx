import { useEffect } from 'react'
import { Sidebar } from './components/catalog/Sidebar'
import { Editor2D } from './components/editor2d/Editor2D'
import { SelectionPanel } from './components/layout/SelectionPanel'
import { Toasts } from './components/layout/Toasts'
import { TopBar } from './components/layout/TopBar'
import { Viewer3D } from './components/viewer3d/Viewer3D'
import { useModelOrchestrator } from './hooks/useModelGeneration'
import { useAppStore } from './store/useAppStore'

const isTyping = (t: EventTarget | null): boolean =>
  t instanceof HTMLElement && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)

/** Measure the floorplan image once a URL is known (e.g. after loading a saved project). */
function useFloorplanSize() {
  const url = useAppStore((s) => s.floorplanUrl)
  const size = useAppStore((s) => s.floorplanSize)
  useEffect(() => {
    if (!url || size) return
    let alive = true
    const img = new Image()
    img.onload = () => alive && useAppStore.getState().setFloorplanSize({ w: img.naturalWidth, h: img.naturalHeight })
    img.src = url
    return () => {
      alive = false
    }
  }, [url, size])
}

function useShortcuts() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target)) return
      const st = useAppStore.getState()
      const mod = e.ctrlKey || e.metaKey
      if (mod && e.key.toLowerCase() === 'z') {
        e.preventDefault()
        if (e.shiftKey) st.redo()
        else st.undo()
      } else if (mod && e.key.toLowerCase() === 'y') {
        e.preventDefault()
        st.redo()
      } else if (mod && e.key.toLowerCase() === 'd') {
        e.preventDefault()
        if (st.selected?.type === 'item') st.duplicateItem(st.selected.id)
      } else if (e.key === 'Delete' || e.key === 'Backspace') {
        if (st.selected) {
          e.preventDefault()
          st.deleteSelected()
        }
      } else if (!mod && e.key.toLowerCase() === 'r') {
        if (st.selected?.type === 'item') st.rotateItem90(st.selected.id)
      } else if (e.key === 'Escape') {
        st.setSelected(null)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
}

export default function App() {
  const viewMode = useAppStore((s) => s.viewMode)
  useModelOrchestrator()
  useFloorplanSize()
  useShortcuts()

  const show2d = viewMode === '2d' || viewMode === 'split'
  const show3d = viewMode === '3d' || viewMode === 'split'

  return (
    <div className="flex h-full flex-col" dir="rtl">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <main className="relative flex min-w-0 flex-1" data-testid="workspace">
          {show2d && (
            <section className={`min-w-0 ${show3d ? 'w-1/2 border-e border-slate-300' : 'w-full'}`}>
              <Editor2D />
            </section>
          )}
          {show3d && (
            <section className={`min-w-0 ${show2d ? 'w-1/2' : 'w-full'}`}>
              <Viewer3D />
            </section>
          )}
          <SelectionPanel />
        </main>
      </div>
      <Toasts />
    </div>
  )
}
