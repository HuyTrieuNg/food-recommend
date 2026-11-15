import { ActionIcon, Badge, Card, Center, Group, Image, Rating, Stack, Text, Tooltip } from '@mantine/core'
import { IconBowlChopsticks, IconMapPin, IconX } from '@tabler/icons-react'
import type { ReactNode } from 'react'
import type { Place } from '../api'
import { useApp } from '../state'

export function ratingColor(r: number | null | undefined) {
  if (r == null) return 'gray'
  if (r >= 8) return 'teal'
  if (r >= 6.5) return 'yellow'
  return 'red'
}

/** Foody chấm thang 10 -> 5 sao, nửa sao = 1 điểm. */
export function RateControl({ place, size = 'sm' }: { place: Place; size?: 'sm' | 'md' | 'lg' }) {
  const { userId, ratings, rate, unrate } = useApp()
  const current = ratings.get(place.id)
  if (userId == null) return null
  return (
    <Group gap={6} wrap="nowrap">
      <Rating
        size={size}
        fractions={2}
        value={current ? current.rating / 2 : 0}
        onChange={(v) => rate(place.id, v * 2)}
      />
      {current && (
        <Tooltip label={current.source === 'data' ? 'Rating từ data Foody' : 'Rating nhập trên demo'}>
          <Badge size="sm" variant={current.source === 'demo' ? 'filled' : 'light'} color={ratingColor(current.rating)}>
            {current.rating.toFixed(1)}
          </Badge>
        </Tooltip>
      )}
      {current?.source === 'demo' && (
        <Tooltip label="Xoá rating">
          <ActionIcon size="sm" variant="subtle" color="gray" onClick={() => unrate(place.id)}>
            <IconX size={14} />
          </ActionIcon>
        </Tooltip>
      )}
    </Group>
  )
}

export function PlaceImage({ src, h }: { src: string | null; h: number }) {
  return src ? (
    <Image src={src} h={h} fit="cover" referrerPolicy="no-referrer" loading="lazy" />
  ) : (
    <Center h={h} bg="var(--mantine-color-default-hover)">
      <IconBowlChopsticks size={40} color="var(--mantine-color-dimmed)" />
    </Center>
  )
}

export function PlaceCard({ place, children }: { place: Place; children?: ReactNode }) {
  const { openPlace } = useApp()
  return (
    <Card withBorder radius="md" padding="sm" h="100%">
      <Card.Section style={{ cursor: 'pointer' }} onClick={() => openPlace(place.id)}>
        <PlaceImage src={place.image} h={140} />
      </Card.Section>
      <Stack gap={6} mt="sm" style={{ flex: 1 }}>
        <Text fw={600} lineClamp={2} style={{ cursor: 'pointer' }} onClick={() => openPlace(place.id)}>
          {place.name}
        </Text>
        <Group gap={4}>
          <Badge size="sm" variant="light" color={ratingColor(place.avg_rating)}>
            ★ {place.avg_rating ? place.avg_rating.toFixed(1) : '–'}
          </Badge>
          <Badge size="sm" variant="default">
            {place.total_reviews} review
          </Badge>
          {place.district && (
            <Badge size="sm" variant="outline" color="gray" leftSection={<IconMapPin size={10} />}>
              {place.district.replace('Quận ', '')}
            </Badge>
          )}
        </Group>
        {children}
      </Stack>
      <Group mt="sm">
        <RateControl place={place} />
      </Group>
    </Card>
  )
}
