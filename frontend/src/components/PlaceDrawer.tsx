import { Anchor, Badge, Button, Divider, Drawer, Group, Image, Loader, Paper, ScrollArea, Stack, Tabs, Text } from '@mantine/core'
import { IconExternalLink, IconMap } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { api, type Place } from '../api'
import { useApp } from '../state'
import { PlaceImage, RateControl, ratingColor } from './PlaceCard'

function SimilarList({ items, label }: { items: { place: Place; score: number }[]; label: string }) {
  const { openPlace } = useApp()
  if (!items.length) return <Text size="sm" c="dimmed">Không có dữ liệu (quán chưa có user chấm chung).</Text>
  return (
    <Stack gap="xs">
      {items.map(({ place, score }) => (
        <Paper key={place.id} withBorder p="xs" style={{ cursor: 'pointer' }} onClick={() => openPlace(place.id)}>
          <Group justify="space-between" wrap="nowrap">
            <div style={{ minWidth: 0 }}>
              <Text size="sm" fw={500} truncate>
                {place.name}
              </Text>
              <Text size="xs" c="dimmed" truncate>
                {place.address}
              </Text>
            </div>
            <Group gap={4} wrap="nowrap">
              <Badge size="sm" variant="light" color={ratingColor(place.avg_rating)}>
                ★ {place.avg_rating?.toFixed(1) ?? '–'}
              </Badge>
              <Badge size="sm" variant="default">
                {label} {score.toFixed(3)}
              </Badge>
            </Group>
          </Group>
        </Paper>
      ))}
    </Stack>
  )
}

export function PlaceDrawer() {
  const { openPlaceId, openPlace } = useApp()
  const { data, isLoading } = useQuery({
    queryKey: ['place', openPlaceId],
    queryFn: () => api.place(openPlaceId!),
    enabled: openPlaceId != null,
  })
  const p = data?.place

  return (
    <Drawer
      opened={openPlaceId != null}
      onClose={() => openPlace(null)}
      position="right"
      size="lg"
      title={<Text fw={700}>{p?.name ?? 'Đang tải…'}</Text>}
      scrollAreaComponent={ScrollArea.Autosize}
    >
      {isLoading || !data || !p ? (
        <Loader />
      ) : (
        <Stack>
          <PlaceImage src={p.image} h={220} />
          <Text size="sm">{p.address}</Text>
          <Group gap="xs">
            <Badge color={ratingColor(p.avg_rating)}>★ {p.avg_rating?.toFixed(2) ?? '–'} trên Foody</Badge>
            <Badge variant="default">{p.total_reviews} review trên Foody</Badge>
            <Badge variant="default">{p.n_ratings} rating trong data</Badge>
          </Group>
          <Group gap="xs">
            {p.url && (
              <Button component="a" href={p.url} target="_blank" size="xs" variant="light" rightSection={<IconExternalLink size={14} />}>
                Foody
              </Button>
            )}
            {p.lat != null && p.lon != null && (
              <Button
                component="a"
                href={`https://www.google.com/maps?q=${p.lat},${p.lon}`}
                target="_blank"
                size="xs"
                variant="light"
                leftSection={<IconMap size={14} />}
              >
                Bản đồ
              </Button>
            )}
          </Group>
          <Group>
            <Text size="sm" fw={500}>
              Chấm điểm của bạn:
            </Text>
            <RateControl place={p} size="md" />
          </Group>
          <Divider />
          <Tabs defaultValue="similar_cb">
            <Tabs.List>
              <Tabs.Tab value="similar_cb">Tương tự (nội dung)</Tabs.Tab>
              <Tabs.Tab value="similar_cf">Tương tự (CF)</Tabs.Tab>
              <Tabs.Tab value="reviews">Review ({data.reviews.length})</Tabs.Tab>
            </Tabs.List>
            <Tabs.Panel value="similar_cb" pt="sm">
              <SimilarList items={data.similar_content} label="cos" />
            </Tabs.Panel>
            <Tabs.Panel value="similar_cf" pt="sm">
              <SimilarList items={data.similar_cf} label="sim" />
            </Tabs.Panel>
            <Tabs.Panel value="reviews" pt="sm">
              <Stack gap="sm">
                {data.reviews.map((r) => (
                  <Paper key={r.id} withBorder p="sm">
                    <Group justify="space-between">
                      <Text size="sm" fw={600}>
                        {r.user_name}
                      </Text>
                      <Badge color={ratingColor(r.rating)}>{r.rating.toFixed(1)}</Badge>
                    </Group>
                    {r.title && (
                      <Text size="sm" fw={500} mt={4}>
                        {r.title}
                      </Text>
                    )}
                    <Text size="sm" c="dimmed" lineClamp={5} style={{ whiteSpace: 'pre-line' }}>
                      {r.text}
                    </Text>
                    {r.pictures.length > 0 && (
                      <Group gap={4} mt={6}>
                        {r.pictures.map((src) => (
                          <Image key={src} src={src} h={64} w={64} radius="sm" fit="cover" referrerPolicy="no-referrer" loading="lazy" />
                        ))}
                      </Group>
                    )}
                    <Group justify="space-between" mt={4}>
                      <Text size="xs" c="dimmed">
                        {r.created_at ? new Date(r.created_at).toLocaleDateString('vi-VN') : ''}
                      </Text>
                      <Anchor size="xs" href={`${p.url ?? ''}/binh-luan-${r.id}`} target="_blank">
                        Xem trên Foody
                      </Anchor>
                    </Group>
                  </Paper>
                ))}
              </Stack>
            </Tabs.Panel>
          </Tabs>
        </Stack>
      )}
    </Drawer>
  )
}
