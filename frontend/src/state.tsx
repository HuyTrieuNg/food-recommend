import { useLocalStorage } from '@mantine/hooks'
import { notifications } from '@mantine/notifications'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'
import { api, type UserRating } from './api'

type Ctx = {
  userId: number | null
  setUserId: (id: number | null) => void
  ratings: Map<number, UserRating>
  rate: (placeId: number, rating: number) => void
  unrate: (placeId: number) => void
  openPlaceId: number | null
  openPlace: (id: number | null) => void
}

const AppCtx = createContext<Ctx | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const [userId, setUserId] = useLocalStorage<number | null>({ key: 'demo-user-id', defaultValue: null, getInitialValueInEffect: false })
  const [openPlaceId, openPlace] = useState<number | null>(null)

  const { data } = useQuery({
    queryKey: ['ratings', userId],
    queryFn: () => api.ratings(userId!),
    enabled: userId != null,
  })
  const ratings = useMemo(() => new Map((data ?? []).map((r) => [r.place.id, r])), [data])

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['ratings', userId] })
    qc.invalidateQueries({ queryKey: ['recs', userId] })
    qc.invalidateQueries({ queryKey: ['user', userId] })
  }
  const onError = (e: Error) => notifications.show({ color: 'red', title: 'Lỗi', message: e.message })

  const rateMut = useMutation({
    mutationFn: ({ placeId, rating }: { placeId: number; rating: number }) => api.rate(userId!, placeId, rating),
    onSuccess: refresh,
    onError,
  })
  const unrateMut = useMutation({
    mutationFn: (placeId: number) => api.unrate(userId!, placeId),
    onSuccess: refresh,
    onError,
  })

  const value: Ctx = {
    userId,
    setUserId,
    ratings,
    rate: (placeId, rating) => rateMut.mutate({ placeId, rating }),
    unrate: (placeId) => unrateMut.mutate(placeId),
    openPlaceId,
    openPlace,
  }
  return <AppCtx.Provider value={value}>{children}</AppCtx.Provider>
}

export function useApp() {
  const ctx = useContext(AppCtx)
  if (!ctx) throw new Error('useApp must be used inside AppProvider')
  return ctx
}
