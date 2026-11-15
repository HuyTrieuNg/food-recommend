import { Alert, Badge, Center, Pagination, SimpleGrid, Stack, Text } from '@mantine/core'
import { useEffect, useState } from 'react'
import { useApp } from '../state'
import { PlaceCard } from './PlaceCard'

const PAGE = 24

export function MyRatingsPanel() {
  const { userId, ratings } = useApp()
  const [page, setPage] = useState(1)
  useEffect(() => setPage(1), [userId])

  const items = [...ratings.values()]
  if (!items.length) {
    return <Alert variant="light">User chưa chấm quán nào. Vào tab Khám phá để chấm điểm.</Alert>
  }
  const totalPages = Math.ceil(items.length / PAGE)
  const current = Math.min(page, totalPages) // xoá rating ở trang cuối có thể làm giảm số trang
  const nDemo = items.filter((r) => r.source === 'demo').length

  return (
    <Stack>
      <Text size="sm" c="dimmed">
        {items.length} rating ({items.length - nDemo} từ data Foody, {nDemo} nhập trên demo). Rating từ data có thể
        chấm đè. Rating nhập trên demo xoá được.
      </Text>
      <SimpleGrid cols={{ base: 1, xs: 2, md: 3, lg: 4 }}>
        {items.slice((current - 1) * PAGE, current * PAGE).map((r) => (
          <PlaceCard key={r.place.id} place={r.place}>
            <Badge size="sm" variant="dot" color={r.source === 'demo' ? 'grape' : 'gray'}>
              {r.source === 'demo' ? 'Nhập trên demo' : 'Data Foody'}
            </Badge>
          </PlaceCard>
        ))}
      </SimpleGrid>
      {totalPages > 1 && (
        <Center>
          <Pagination
            total={totalPages}
            value={current}
            onChange={(p) => {
              setPage(p)
              window.scrollTo({ top: 0, behavior: 'smooth' })
            }}
          />
        </Center>
      )}
    </Stack>
  )
}
