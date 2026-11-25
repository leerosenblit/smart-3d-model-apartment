import { useAppStore } from '../../store/useAppStore'

export function Toasts() {
  const toasts = useAppStore((s) => s.toasts)
  const dismiss = useAppStore((s) => s.dismissToast)
  return (
    <div className="pointer-events-none fixed inset-x-0 top-3 z-[60] flex flex-col items-center gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          onClick={() => dismiss(t.id)}
          className={`pointer-events-auto cursor-pointer rounded-lg px-4 py-2 text-sm font-medium text-white shadow-lg ${
            t.kind === 'error' ? 'bg-red-600' : t.kind === 'success' ? 'bg-emerald-600' : 'bg-slate-800'
          }`}
          role="status"
        >
          {t.message}
        </div>
      ))}
    </div>
  )
}
