import { Badge, Button, Group, Modal, Select, Stack, Text, TextInput } from '@mantine/core'
import { useDebouncedValue, useDisclosure } from '@mantine/hooks'
import { IconUserPlus } from '@tabler/icons-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type User } from '../api'
import { useApp } from '../state'

export function UserPicker() {
  const { userId, setUserId } = useApp()
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [searchDeb] = useDebouncedValue(search, 300)
  const [opened, { open, close }] = useDisclosure(false)
  const [newName, setNewName] = useState('')

  const { data: users = [] } = useQuery({ queryKey: ['users', searchDeb], queryFn: () => api.users(searchDeb) })
  const { data: current } = useQuery({
    queryKey: ['user', userId],
    queryFn: () => api.user(userId!),
    enabled: userId != null,
    retry: false,
  })

  const create = useMutation({
    mutationFn: api.createUser,
    onSuccess: (u) => {
      qc.invalidateQueries({ queryKey: ['users'] })
      setUserId(u.id)
      setNewName('')
      close()
    },
  })

  const byId = new Map<number, User>(users.map((u) => [u.id, u]))
  if (current) byId.set(current.id, current)
  const options = [...byId.values()].map((u) => ({
    value: String(u.id),
    label: `${u.name}${u.is_new ? ' (mới)' : ''} · ${u.n_ratings} rating`,
  }))

  return (
    <Group gap="xs" wrap="nowrap">
      <Select
        w={{ base: 200, sm: 320 }}
        searchable
        placeholder="Chọn user…"
        data={options}
        value={userId != null ? String(userId) : null}
        onChange={(v) => v && setUserId(Number(v))}
        allowDeselect={false}
        searchValue={search}
        onSearchChange={setSearch}
        filter={({ options }) => options}
        nothingFoundMessage="Không tìm thấy"
        maxDropdownHeight={400}
      />
      {current?.level && (
        <Badge variant="light" visibleFrom="sm">
          {current.level}
        </Badge>
      )}
      <Button leftSection={<IconUserPlus size={16} />} variant="light" onClick={open}>
        User mới
      </Button>
      <Modal opened={opened} onClose={close} title="Tạo user mới">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (newName.trim()) create.mutate(newName.trim())
          }}
        >
          <Stack>
            <Text size="sm" c="dimmed">
              User mới chưa có rating (cold-start). Hãy chấm điểm vài quán để xem gợi ý thay đổi.
            </Text>
            <TextInput label="Tên" value={newName} onChange={(e) => setNewName(e.currentTarget.value)} data-autofocus />
            <Button type="submit" loading={create.isPending}>
              Tạo
            </Button>
          </Stack>
        </form>
      </Modal>
    </Group>
  )
}
