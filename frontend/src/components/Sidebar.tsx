import { NavLink } from 'react-router-dom'
import { MessageSquare, Activity, BarChart2, BookOpen, Sliders, Info, ChevronLeft, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { cn } from '../lib/utils'

interface NavItem {
  to: string
  icon: React.ReactNode
  label: string
  end?: boolean
}

const NAV_ITEMS: NavItem[] = [
  { to: '/', icon: <MessageSquare size={16} />, label: 'Ask', end: true },
  { to: '/dataset', icon: <Activity size={16} />, label: 'Dataset Health' },
  { to: '/analysis', icon: <BarChart2 size={16} />, label: 'Analysis' },
  { to: '/evidence', icon: <BookOpen size={16} />, label: 'Evidence' },
  { to: '/config', icon: <Sliders size={16} />, label: 'Config' },
  { to: '/about', icon: <Info size={16} />, label: 'About' },
]

const PROPOSED_ENABLED = import.meta.env.VITE_ENABLE_PROPOSED === 'true'
const PROPOSED_ITEMS: NavItem[] = [
  { to: '/waveforms', icon: <Activity size={16} />, label: 'Waveforms' },
  { to: '/tool-wear', icon: <BarChart2 size={16} />, label: 'Tool Wear' },
]

interface SidebarProps {
  className?: string
}

export function Sidebar({ className }: SidebarProps) {
  const [collapsed, setCollapsed] = useState(false)

  return (
    <aside
      className={cn(
        'flex flex-col shrink-0 border-r border-[var(--border)] bg-[var(--surface)] transition-all duration-200 select-none',
        collapsed ? 'w-12' : 'w-48',
        className,
      )}
    >
      <nav className="flex flex-col gap-0.5 p-2 flex-1" aria-label="Main navigation">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors no-underline',
                isActive
                  ? 'bg-[var(--accent-dim)] text-[var(--accent)]'
                  : 'text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--surface-2)]',
              )
            }
            aria-current={undefined}
          >
            <span className="shrink-0">{item.icon}</span>
            {!collapsed && <span className="truncate">{item.label}</span>}
          </NavLink>
        ))}

        {PROPOSED_ENABLED && (
          <>
            <div className={cn('px-2.5 pt-3 pb-1', collapsed && 'px-1')}>
              {!collapsed && (
                <span className="text-[10px] font-semibold uppercase tracking-widest text-[var(--muted)]">Preview</span>
              )}
            </div>
            {PROPOSED_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  cn(
                    'flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors no-underline',
                    isActive
                      ? 'bg-[var(--accent-dim)] text-[var(--accent)]'
                      : 'text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--surface-2)]',
                  )
                }
              >
                <span className="shrink-0">{item.icon}</span>
                {!collapsed && <span className="truncate">{item.label}</span>}
              </NavLink>
            ))}
          </>
        )}
      </nav>

      <div className="p-2 border-t border-[var(--border)]">
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="w-full flex items-center justify-center p-2 rounded-md text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--surface-2)] transition-colors"
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <ChevronRight size={15} /> : <ChevronLeft size={15} />}
        </button>
      </div>
    </aside>
  )
}
