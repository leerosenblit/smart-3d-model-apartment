import { createRoot } from 'react-dom/client'
import App from './App'
import { useAppStore } from './store/useAppStore'
import './index.css'

// Dev-only handle for debugging / automated browser checks.
if (import.meta.env.DEV) (window as unknown as { __store: typeof useAppStore }).__store = useAppStore

createRoot(document.getElementById('root')!).render(<App />)
