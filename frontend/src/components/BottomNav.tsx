import { NavLink } from 'react-router-dom'
import { MessageSquare, Activity, BarChart2, BookOpen, Sliders } from 'lucide-react'
import { cn } from '../lib/utils'

const ITEMS = [
  { to: '/', icon: <MessageSquare size={18} />, label: 'Ask', end: true },
  { to: '/dataset', icon: <Activity size={18} />, label: 'Dataset' },
  { to: '/analysis', icon: <BarChart2 size={18} />, label: 'Analysis' },
  { to: '/evidence', icon: <BookOpen size={18} />, label: 'Evidence' },
  { to: '/config', icon: <Sliders size={18} />, label: 'Config' },
]

interface BottomNavProps {
  className?: string
}

export function BottomNav({ className }: BottomNavProps) {
  return (
    <nav
      className={cn(
        'flex items-stretch border-t border-[var(--border)] bg-[var(--surface)] shrink-0',
        className,
      )}
      aria-label="Mobile navigation"
    >
      {ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) =>
            cn(
              'flex-1 flex flex-col items-center justify-center gap-0.5 py-2 text-[10px] font-medium no-underline transition-colors',
              isActive ? 'text-[var(--accent)]' : 'text-[var(--muted)]',
            )
          }
        >
          {item.icon}
          {item.label}
        </NavLink>
      ))}
    </nav>
  )
}
