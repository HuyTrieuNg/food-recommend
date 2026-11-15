import { Center, Group, Loader, Pagination, SegmentedControl, Select, SimpleGrid, Stack, Text, TextInput } from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { IconSearch } from '@tabler/icons-react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api'
import { PlaceCard } from './PlaceCard'

const PAGE = 24

export function ExplorePanel() {
  const [q, setQ] = useState('')
  const [district, setDistrict] = useState<string | null>(null)
  const [sort, setSort] = useState('popular')
  const [page, setPage] = useState(1)
  const [qDeb] = useDebouncedValue(q, 300)

  const { data: districts } = useQuery({ queryKey: ['districts'], queryFn: api.districts, staleTime: Infinity })
  const { data, isFetching } = useQuery({
    queryKey: ['places', qDeb, district, sort, page],
    queryFn: () => api.places({ q: qDeb, district, sort, offset: (page - 1) * PAGE, limit: PAGE }),
    placeholderData: keepPreviousData,
  })

  const reset = <T,>(fn: (v: T) => void) => (v: T) => {
    fn(v)
    setPage(1)
  }

  return (
    <Stack>
      <Group align="end">
        <TextInput
          style={{ flex: 1, minWidth: 220 }}
          leftSection={<IconSearch size={16} />}
          placeholder="Tìm tên quán, món, địa chỉ (không cần dấu)…"
          value={q}
          onChange={(e) => reset(setQ)(e.currentTarget.value)}
        />
        <Select
          placeholder="Tất cả quận"
          clearable
          data={districts ?? []}
          value={district}
          onChange={reset(setDistrict)}
          w={200}
        />
        <SegmentedControl
          value={sort}
          onChange={reset(setSort)}
          data={[
            { value: 'popular', label: 'Phổ biến' },
            { value: 'rating', label: 'Điểm cao' },
            { value: 'reviews', label: 'Nhiều review' },
          ]}
        />
      </Group>
      <Group gap="xs">
        <Text size="sm" c="dimmed">
          {data?.total ?? 0} quán
        </Text>
        {isFetching && <Loader size="xs" />}
      </Group>
      <SimpleGrid cols={{ base: 1, xs: 2, md: 3, lg: 4 }}>
        {data?.items.map((p) => <PlaceCard key={p.id} place={p} />)}
      </SimpleGrid>
      {data && data.total > PAGE && (
        <Center>
          <Pagination
            total={Math.ceil(data.total / PAGE)}
            value={page}
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
