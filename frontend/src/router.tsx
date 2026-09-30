import { createBrowserRouter } from 'react-router-dom'
import { Layout } from './components/Layout'
import { Skeleton } from './components/Skeleton'

// Shown in the Layout outlet while a lazily loaded page chunk downloads
function PageSkeleton() {
  return (
    <div className="p-4 md:p-6 space-y-4 max-w-4xl mx-auto w-full" aria-busy="true" aria-label="Loading page">
      <Skeleton className="h-6 w-40" />
      <Skeleton className="h-40 w-full" />
      <Skeleton className="h-24 w-full" />
    </div>
  )
}

type PageModule = Record<string, React.ComponentType>
function page(load: () => Promise<PageModule>, name: string) {
  return {
    HydrateFallback: PageSkeleton,
    lazy: () => load().then((m) => ({ Component: m[name] })),
  }
}

const PROPOSED_ENABLED = import.meta.env.VITE_ENABLE_PROPOSED === 'true'

const proposedRoutes = PROPOSED_ENABLED
  ? [
      {
        path: '/waveforms',
        ...page(() => import('./pages/proposed/WaveformsPage'), 'WaveformsPage'),
      },
      {
        path: '/tool-wear',
        ...page(() => import('./pages/proposed/ToolWearPage'), 'ToolWearPage'),
      },
    ]
  : []

export const router = createBrowserRouter([
  {
    path: '/',
    element: <Layout />,
    children: [
      // Each page is its own chunk, loaded on first navigation
      { index: true, ...page(() => import('./pages/AskPage'), 'AskPage') },
      { path: 'dataset', ...page(() => import('./pages/DatasetPage'), 'DatasetPage') },
      { path: 'analysis', ...page(() => import('./pages/AnalysisPage'), 'AnalysisPage') },
      { path: 'evidence', ...page(() => import('./pages/EvidencePage'), 'EvidencePage') },
      { path: 'config', ...page(() => import('./pages/ConfigPage'), 'ConfigPage') },
      { path: 'about', ...page(() => import('./pages/AboutPage'), 'AboutPage') },
      ...proposedRoutes,
    ],
  },
])
