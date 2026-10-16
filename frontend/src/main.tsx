import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { AppBoundary } from './components/AppBoundary'
import './index.css'
import { registerServiceWorker } from './pwa'
import { installStaleChunkReload } from './staleChunks'

installStaleChunkReload()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppBoundary>
      <App />
    </AppBoundary>
  </StrictMode>,
)

registerServiceWorker()
