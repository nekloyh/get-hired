import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// Every face is glyph-verified for full Vietnamese (đ, horn vowels, stacked diacritics) — see
// docs/design/brand.md. Phudu carries display, Be Vietnam Pro carries UI text, JetBrains Mono
// carries every number and metadata strip.
import '@fontsource-variable/phudu'
import '@fontsource/be-vietnam-pro/400.css'
import '@fontsource/be-vietnam-pro/500.css'
import '@fontsource/be-vietnam-pro/600.css'
import '@fontsource/be-vietnam-pro/700.css'
import '@fontsource-variable/jetbrains-mono'
import { App } from './App'
import './styles.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
