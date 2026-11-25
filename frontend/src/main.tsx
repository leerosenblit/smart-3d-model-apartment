import { createRoot } from 'react-dom/client'
import App from './App'
import { useAppStore } from './store/useAppStore'
import './index.css'

// Dev-only handle for debugging / automated browser checks.
if (import.meta.env.DEV) (window as unknown as { __store: typeof useAppStore }).__store = useAppStore

const root = createRoot(document.getElementById('root')!)
if (import.meta.env.DEV && new URLSearchParams(window.location.search).has('gallery')) {
  // dev-only model review page (never part of the production bundle path)
  void import('./dev/ModelGallery').then((m) => root.render(<m.default />))
} else {
  root.render(<App />)
}
