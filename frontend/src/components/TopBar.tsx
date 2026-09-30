import { useState, useEffect } from 'react'
import { Sun, Moon, Settings, Database } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { StatusDot } from './StatusDot'
import { Button } from './ui/button'
import { pingChat, pingCore } from '../api/client'
import { getSettings, updateSettings, subscribe } from '../store/sessionStore'

export function TopBar({ onSettingsOpen }: { onSettingsOpen: () => void }) {
  const [settings, setSettings] = useState(getSettings)

  useEffect(() => {
    return subscribe(() => setSettings(getSettings()))
  }, [])

  const { data: chatOnline = null } = useQuery({
    queryKey: ['ping-chat'],
    queryFn: pingChat,
    refetchInterval: 10_000,
    refetchIntervalInBackground: false,
    retry: false,
    staleTime: 8_000,
  })

  const { data: coreOnline = null } = useQuery({
    queryKey: ['ping-core'],
    queryFn: pingCore,
    refetchInterval: 10_000,
    refetchIntervalInBackground: false,
    retry: false,
    staleTime: 8_000,
  })

  const toggleTheme = () => {
    const next = settings.theme === 'dark' ? 'light' : 'dark'
    updateSettings({ theme: next })
    document.documentElement.setAttribute('data-theme', next)
  }

  return (
    <header
      className="flex items-center justify-between px-4 h-11 border-b border-[var(--border)] bg-[var(--surface)] shrink-0"
      style={{ zIndex: 40 }}
    >
      <Link to="/" className="flex items-center gap-2 text-[var(--text)] no-underline">
        <Database size={16} className="text-[var(--accent)]" />
        <span className="text-sm font-semibold tracking-tight">Institutional Memory</span>
        <span className="hidden sm:inline text-[11px] text-[var(--muted)] font-mono ml-1">DAQ Condition Intelligence</span>
      </Link>

      <div className="flex items-center gap-3">
        <div className="hidden sm:flex items-center gap-3">
          <StatusDot online={chatOnline} label="chat" />
          <StatusDot online={coreOnline} label="core" />
        </div>

        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon" onClick={toggleTheme} aria-label="Toggle theme">
            {settings.theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
          </Button>
          <Button variant="ghost" size="icon" onClick={onSettingsOpen} aria-label="Open settings">
            <Settings size={15} />
          </Button>
        </div>
      </div>
    </header>
  )
}
