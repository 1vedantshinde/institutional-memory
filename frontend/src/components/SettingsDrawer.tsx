import { useState, useEffect } from 'react'
import { X } from 'lucide-react'
import { Button } from './ui/button'
import { Input } from './ui/input'
import { Label } from './ui/label'
import { Switch } from './ui/switch'
import { getSettings, updateSettings, subscribe } from '../store/sessionStore'
import { cn } from '../lib/utils'

interface SettingsDrawerProps {
  open: boolean
  onClose: () => void
}

export function SettingsDrawer({ open, onClose }: SettingsDrawerProps) {
  const [settings, setSettings] = useState(getSettings)
  const [localChat, setLocalChat] = useState(settings.chatApiUrl)
  const [localCore, setLocalCore] = useState(settings.coreApiUrl)
  const [localDataset, setLocalDataset] = useState(settings.datasetPath)
  const [localConfig, setLocalConfig] = useState(settings.configPath)

  useEffect(() => {
    return subscribe(() => {
      const s = getSettings()
      setSettings(s)
    })
  }, [])

  useEffect(() => {
    if (open) {
      const s = getSettings()
      setLocalChat(s.chatApiUrl)
      setLocalCore(s.coreApiUrl)
      setLocalDataset(s.datasetPath)
      setLocalConfig(s.configPath)
    }
  }, [open])

  const save = () => {
    updateSettings({
      chatApiUrl: localChat,
      coreApiUrl: localCore,
      datasetPath: localDataset,
      configPath: localConfig,
    })
    onClose()
  }

  const toggleOverload = (v: boolean) => {
    updateSettings({ simulateLlmOverload: v })
  }

  return (
    <>
      {open && (
        <div
          className="fixed inset-0 z-40 bg-black/50"
          onClick={onClose}
          aria-hidden="true"
        />
      )}
      <aside
        className={cn(
          'fixed top-0 right-0 h-full w-80 z-50 bg-[var(--surface)] border-l border-[var(--border)] flex flex-col shadow-2xl transition-transform duration-200',
          open ? 'translate-x-0' : 'translate-x-full',
        )}
        aria-label="Settings"
        role="dialog"
        aria-modal="true"
      >
        <div className="flex items-center justify-between px-4 h-11 border-b border-[var(--border)] shrink-0">
          <span className="text-sm font-semibold">Settings</span>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close settings">
            <X size={15} />
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-5">
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-widest text-[var(--muted)] mb-3">API Endpoints</h3>
            <div className="flex flex-col gap-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="chat-url">Chat server URL</Label>
                <Input
                  id="chat-url"
                  value={localChat}
                  onChange={(e) => setLocalChat(e.target.value)}
                  placeholder="http://localhost:8000"
                  className="font-mono text-xs"
                />
                <p className="text-[11px] text-[var(--muted)]">POST /chat, GET /chat/status</p>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="core-url">Core API URL</Label>
                <Input
                  id="core-url"
                  value={localCore}
                  onChange={(e) => setLocalCore(e.target.value)}
                  placeholder="http://localhost:8001"
                  className="font-mono text-xs"
                />
                <p className="text-[11px] text-[var(--muted)]">/ingest /profile /analyse /query /config</p>
              </div>
            </div>
          </section>

          <section>
            <h3 className="text-xs font-semibold uppercase tracking-widest text-[var(--muted)] mb-3">Default Paths</h3>
            <div className="flex flex-col gap-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="dataset-path">Dataset folder</Label>
                <Input
                  id="dataset-path"
                  value={localDataset}
                  onChange={(e) => setLocalDataset(e.target.value)}
                  className="font-mono text-xs"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="config-path">Config path</Label>
                <Input
                  id="config-path"
                  value={localConfig}
                  onChange={(e) => setLocalConfig(e.target.value)}
                  className="font-mono text-xs"
                />
              </div>
            </div>
          </section>

          <section>
            <h3 className="text-xs font-semibold uppercase tracking-widest text-[var(--muted)] mb-3">Testing</h3>
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-sm">Simulate LLM overload</p>
                <p className="text-[11px] text-[var(--muted)]">Forces 503 on /chat and /query responses</p>
              </div>
              <Switch
                checked={settings.simulateLlmOverload}
                onCheckedChange={toggleOverload}
                aria-label="Simulate LLM overload"
              />
            </div>
          </section>

          <section>
            <h3 className="text-xs font-semibold uppercase tracking-widest text-[var(--muted)] mb-3">CORS Note</h3>
            <p className="text-[11px] text-[var(--muted)] leading-relaxed">
              If the browser shows CORS errors, add <code className="font-mono bg-[var(--surface-2)] px-1 rounded">CORSMiddleware</code> to both backends allowing <code className="font-mono bg-[var(--surface-2)] px-1 rounded">http://localhost:5173</code>. Alternatively, use the Vite proxy at <code className="font-mono bg-[var(--surface-2)] px-1 rounded">/chat-api</code> and <code className="font-mono bg-[var(--surface-2)] px-1 rounded">/core-api</code>.
            </p>
          </section>
        </div>

        <div className="flex gap-2 p-4 border-t border-[var(--border)] shrink-0">
          <Button variant="ghost" size="md" onClick={onClose} className="flex-1">Cancel</Button>
          <Button size="md" onClick={save} className="flex-1">Save</Button>
        </div>
      </aside>
    </>
  )
}
