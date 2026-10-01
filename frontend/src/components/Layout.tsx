import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { TopBar } from './TopBar'
import { Sidebar } from './Sidebar'
import { BottomNav } from './BottomNav'
import { SettingsDrawer } from './SettingsDrawer'

export function Layout() {
  const [settingsOpen, setSettingsOpen] = useState(false)

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-[var(--bg)]">
      <TopBar onSettingsOpen={() => setSettingsOpen(true)} />

      <div className="flex flex-1 overflow-hidden">
        {/* Desktop sidebar */}
        <Sidebar className="hidden md:flex" />

        {/* Main content area */}
        <main className="flex-1 overflow-hidden flex flex-col">
          <Outlet />
        </main>
      </div>

      {/* Mobile bottom nav */}
      <BottomNav className="md:hidden" />

      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />

      {/* ARIA live region for status announcements */}
      <div
        id="live-announcer"
        role="status"
        aria-live="polite"
        aria-atomic="true"
        className="sr-only"
      />
    </div>
  )
}
