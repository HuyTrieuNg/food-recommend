export type Place = {
  id: number
  name: string
  address: string | null
  district: string | null
  lat: number | null
  lon: number | null
  avg_rating: number | null
  total_reviews: number
  url: string | null
  image: string | null
  n_ratings: number
}

export type User = {
  id: number
  name: string
  n_ratings: number
  level: string | null
  is_new: boolean
}

export type ModelName = 'cb' | 'cf' | 'hybrid'

export type RecItem = {
  place: Place
  score: number
  cb: number | null
  cf: number | null
  cf_supported: boolean
  reason: { place_id: number; name: string; rating: number } | null
}

export type RecResponse = {
  model: ModelName | 'popular'
  n_user_ratings: number
  total: number
  offset: number
  took_ms: number
  items: RecItem[]
}

export type UserRating = { place: Place; rating: number; source: 'data' | 'demo' }

export type Review = {
  id: number
  user_id: number
  user_name: string
  rating: number
  title: string | null
  text: string | null
  created_at: string | null
  pictures: string[]
}

export type PlaceDetail = {
  place: Place
  reviews: Review[]
  similar_content: { place: Place; score: number }[]
  similar_cf: { place: Place; score: number }[]
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail ?? res.statusText)
  }
  return res.json()
}

const qs = (params: Record<string, string | number | undefined | null>) =>
  new URLSearchParams(
    Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== null && v !== '')
      .map(([k, v]) => [k, String(v)]),
  ).toString()

export const api = {
  users: (q: string) => req<User[]>(`/users?${qs({ q, limit: 50 })}`),
  user: (id: number) => req<User>(`/users/${id}`),
  createUser: (name: string) => req<User>('/users', { method: 'POST', body: JSON.stringify({ name }) }),
  ratings: (uid: number) => req<UserRating[]>(`/users/${uid}/ratings`),
  rate: (uid: number, place_id: number, rating: number) =>
    req(`/users/${uid}/ratings`, { method: 'POST', body: JSON.stringify({ place_id, rating }) }),
  unrate: (uid: number, place_id: number) => req(`/users/${uid}/ratings/${place_id}`, { method: 'DELETE' }),
  recommend: (uid: number, model: ModelName, alpha: number, offset: number, limit: number) =>
    req<RecResponse>(`/users/${uid}/recommendations?${qs({ model, alpha, offset, limit })}`),
  districts: () => req<string[]>('/districts'),
  places: (p: { q?: string; district?: string | null; sort?: string; offset?: number; limit?: number }) =>
    req<{ total: number; items: Place[] }>(`/places?${qs(p)}`),
  place: (id: number) => req<PlaceDetail>(`/places/${id}`),
}
