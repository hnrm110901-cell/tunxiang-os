import { useQuery } from '@tanstack/react-query'
import { listApplications } from '@/api/applications'
import type { ApplicationListQuery } from '@/types/application'

export function useApplications(query: ApplicationListQuery = {}) {
  return useQuery({
    queryKey: ['devforge', 'applications', query],
    queryFn: () => listApplications(query),
    staleTime: 30_000,
  })
}
