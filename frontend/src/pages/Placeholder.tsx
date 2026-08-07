import { Construction } from 'lucide-react'
import { EmptyState } from '@/components/ui/EmptyState'

/**
 * Honest scaffolding. Each route that is not yet built says which
 * implementation step delivers it, rather than showing a fake screen.
 */
export function Placeholder({ title, step, describes }: {
  title: string
  step: string
  describes: string
}) {
  return (
    <div className="p-6">
      <div className="surface">
        <EmptyState
          icon={<Construction className="h-8 w-8" />}
          title={title}
          body={`${describes} Arrives in ${step}. The data model, routes and design system it needs are already in place.`}
        />
      </div>
    </div>
  )
}
