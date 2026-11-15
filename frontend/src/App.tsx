import { ActionIcon, Alert, AppShell, Container, Group, Tabs, Title, useMantineColorScheme } from '@mantine/core'
import { IconMoon, IconSparkles, IconStar, IconSearch, IconSun, IconToolsKitchen2 } from '@tabler/icons-react'
import { useState } from 'react'
import { ExplorePanel } from './components/ExplorePanel'
import { MyRatingsPanel } from './components/MyRatingsPanel'
import { PlaceDrawer } from './components/PlaceDrawer'
import { RecommendPanel } from './components/RecommendPanel'
import { UserPicker } from './components/UserPicker'
import { useApp } from './state'

export default function App() {
  const { userId, ratings } = useApp()
  const { colorScheme, toggleColorScheme } = useMantineColorScheme()
  const [tab, setTab] = useState<string | null>('recs')
  const activeTab = userId == null ? 'explore' : tab

  return (
    <AppShell header={{ height: 64 }} padding="md">
      <AppShell.Header>
        <Container size="xl" h="100%">
          <Group h="100%" justify="space-between" wrap="nowrap">
            <Group gap="xs" wrap="nowrap">
              <IconToolsKitchen2 color="var(--mantine-color-orange-6)" />
              <Title order={4} visibleFrom="sm">
                Food Recommend · Đà Nẵng
              </Title>
            </Group>
            <Group gap="xs" wrap="nowrap">
              <UserPicker />
              <ActionIcon variant="default" size="lg" onClick={toggleColorScheme} aria-label="Đổi giao diện">
                {colorScheme === 'dark' ? <IconSun size={18} /> : <IconMoon size={18} />}
              </ActionIcon>
            </Group>
          </Group>
        </Container>
      </AppShell.Header>

      <AppShell.Main>
        <Container size="xl">
          {userId == null && (
            <Alert mb="md" variant="light">
              Chọn một user có sẵn trong data (đã sắp theo số rating) hoặc tạo user mới ở góc trên để xem gợi ý.
            </Alert>
          )}
          <Tabs value={activeTab} onChange={setTab} keepMounted={false}>
            <Tabs.List mb="md">
              <Tabs.Tab value="recs" leftSection={<IconSparkles size={16} />} disabled={userId == null}>
                Gợi ý cho bạn
              </Tabs.Tab>
              <Tabs.Tab value="explore" leftSection={<IconSearch size={16} />}>
                Khám phá quán
              </Tabs.Tab>
              <Tabs.Tab value="mine" leftSection={<IconStar size={16} />} disabled={userId == null}>
                Đã chấm ({ratings.size})
              </Tabs.Tab>
            </Tabs.List>
            <Tabs.Panel value="recs">{userId != null && <RecommendPanel />}</Tabs.Panel>
            <Tabs.Panel value="explore">
              <ExplorePanel />
            </Tabs.Panel>
            <Tabs.Panel value="mine">{userId != null && <MyRatingsPanel />}</Tabs.Panel>
          </Tabs>
        </Container>
      </AppShell.Main>
      <PlaceDrawer />
    </AppShell>
  )
}
