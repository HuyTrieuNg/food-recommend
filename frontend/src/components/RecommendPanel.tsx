import { Alert, Badge, Center, Group, Loader, Pagination, SegmentedControl, SimpleGrid, Slider, Stack, Tabs, Text, Tooltip } from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { IconInfoCircle } from '@tabler/icons-react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, type ModelName, type RecItem } from '../api'
import { useApp } from '../state'
import { PlaceCard } from './PlaceCard'

const MODEL_INFO: Record<ModelName, { label: string; desc: string }> = {
  cb: {
    label: 'Content-based',
    desc: 'TF-IDF trên tên quán, quận và nội dung review. Profile của bạn là trung bình các quán đã chấm (chấm ≥ 6 kéo lại gần, < 6 đẩy ra xa) và hệ thống gợi ý quán có nội dung giống profile nhất.',
  },
  cf: {
    label: 'Collaborative',
    desc: 'Item-based KNN trên phần dư baseline (μ + b_user + b_item). Một quán được gợi ý khi những người chấm giống bạn ở các quán bạn đã chấm cũng chấm quán đó cao. Điểm hiển thị là rating dự đoán (thang 10).',
  },
  hybrid: {
    label: 'Hybrid',
    desc: 'Chuẩn hoá min-max điểm của hai model rồi trộn: α·CB + (1−α)·CF.',
  },
}

function RecExtra({ item, model }: { item: RecItem; model: string }) {
  return (
    <Stack gap={4}>
      <Group gap={4}>
        {model === 'hybrid' && (
          <Badge size="sm" color="grape">
            score {item.score.toFixed(3)}
          </Badge>
        )}
        {item.cb != null && (
          <Tooltip label="Độ tương đồng nội dung với profile của bạn">
            <Badge size="sm" variant="light" color="blue">
              CB {item.cb.toFixed(3)}
            </Badge>
          </Tooltip>
        )}
        {item.cf != null && (
          <Tooltip label={item.cf_supported ? 'Rating dự đoán bởi KNN' : 'Không có láng giềng, chỉ dùng baseline'}>
            <Badge size="sm" variant={item.cf_supported ? 'light' : 'outline'} color="orange">
              CF {item.cf.toFixed(2)}
              {!item.cf_supported && ' (baseline)'}
            </Badge>
          </Tooltip>
        )}
      </Group>
      {item.reason && (
        <Text size="xs" c="dimmed" lineClamp={2}>
          Vì bạn đã chấm <b>{item.reason.name}</b> {item.reason.rating.toFixed(1)}
        </Text>
      )}
    </Stack>
  )
}

export function RecommendPanel() {
  const { userId } = useApp()
  const [model, setModel] = useState<ModelName>('hybrid')
  const [alpha, setAlpha] = useState(0.5)
  const [pageSize, setPageSize] = useState('24')
  const [page, setPage] = useState(1)
  const [alphaDeb] = useDebouncedValue(alpha, 250)

  // đổi user / model / α / số quán mỗi trang -> quay về trang 1
  useEffect(() => setPage(1), [userId, model, alphaDeb, pageSize])

  const size = Number(pageSize)
  const { data, isFetching, error } = useQuery({
    queryKey: ['recs', userId, model, model === 'hybrid' ? alphaDeb : null, page, size],
    queryFn: () => api.recommend(userId!, model, alphaDeb, (page - 1) * size, size),
    enabled: userId != null,
    placeholderData: keepPreviousData,
  })
  const totalPages = data ? Math.max(1, Math.ceil(data.total / size)) : 1

  const changePage = (p: number) => {
    setPage(p)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return (
    <Stack>
      <Tabs value={model} onChange={(v) => v && setModel(v as ModelName)} variant="pills">
        <Tabs.List>
          {(Object.keys(MODEL_INFO) as ModelName[]).map((m) => (
            <Tabs.Tab key={m} value={m}>
              {MODEL_INFO[m].label}
            </Tabs.Tab>
          ))}
          <Group ml="auto" gap="xs">
            <Text size="sm" c="dimmed">
              Mỗi trang
            </Text>
            <SegmentedControl size="xs" value={pageSize} onChange={setPageSize} data={['12', '24', '48']} />
          </Group>
        </Tabs.List>
      </Tabs>

      <Alert variant="light" icon={<IconInfoCircle />} p="sm">
        <Text size="sm">{MODEL_INFO[model].desc}</Text>
        {model === 'hybrid' && (
          <Group mt="sm" gap="md" wrap="nowrap">
            <Text size="sm" w={60}>
              CF
            </Text>
            <Slider
              style={{ flex: 1 }}
              min={0}
              max={1}
              step={0.05}
              value={alpha}
              onChange={setAlpha}
              label={(v) => `α = ${v.toFixed(2)}`}
              marks={[{ value: 0 }, { value: 0.5 }, { value: 1 }]}
            />
            <Text size="sm" w={60} ta="right">
              CB
            </Text>
          </Group>
        )}
      </Alert>

      {error && <Alert color="red">{(error as Error).message}</Alert>}
      {data?.model === 'popular' && (
        <Alert color="yellow" variant="light">
          User chưa có rating đủ để cá nhân hoá (cold-start), nên đang hiển thị <b>quán phổ biến</b> (Bayesian average). Hãy
          chấm điểm vài quán ở tab Khám phá.
        </Alert>
      )}
      {data && (
        <Group gap="xs">
          <Text size="xs" c="dimmed">
            Hạng {data.total ? data.offset + 1 : 0}–{data.offset + data.items.length} / top {data.total} · dựa trên{' '}
            {data.n_user_ratings} rating · {data.took_ms} ms
          </Text>
          {isFetching && <Loader size="xs" />}
        </Group>
      )}
      {!data && isFetching && <Loader />}

      <SimpleGrid cols={{ base: 1, xs: 2, md: 3, lg: 4 }} style={{ opacity: isFetching ? 0.6 : 1 }}>
        {data?.items.map((it) => (
          <PlaceCard key={it.place.id} place={it.place}>
            {data.model !== 'popular' && <RecExtra item={it} model={data.model} />}
          </PlaceCard>
        ))}
      </SimpleGrid>
      {totalPages > 1 && (
        <Center>
          <Pagination total={totalPages} value={page} onChange={changePage} />
        </Center>
      )}
    </Stack>
  )
}
