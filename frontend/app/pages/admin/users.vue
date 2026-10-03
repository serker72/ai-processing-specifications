<template>
  <div class="page-container">
    <h1>Управление пользователями</h1>

    <div class="mb-5">
      <button class="btn-secondary" :disabled="isLoading" @click="loadUsers">
        {{ isLoading ? 'Обновление...' : 'Обновить' }}
      </button>
    </div>

    <div class="table-wrapper">
      <table v-if="users.length || showSkeleton" class="data-table">
        <thead>
          <tr>
            <th>Email</th>
            <th>Роль</th>
            <th>Дата создания</th>
          </tr>
        </thead>
        <tbody>
          <template v-if="showSkeleton">
            <CommonTableSkeleton :columns="3" />
          </template>
          <template v-else>
            <tr v-for="user in users" :key="user.id">
              <td>{{ user.email }}</td>
              <td>
                <!-- Роль меняется сразу; при ошибке список перезагружаем,
                     чтобы выбор отражал реальное состояние backend -->
                <select
                  v-model="user.role"
                  :disabled="isBusy(user) || user.id === currentUserId"
                  @change="updateRole(user)"
                >
                  <option value="admin">Admin</option>
                  <option value="manager">Manager</option>
                </select>
                <span v-if="user.id === currentUserId" class="text-muted text-xs ml-2">это вы</span>
              </td>
              <td>{{ formatDate(user.created_at) }}</td>
            </tr>
          </template>
        </tbody>
      </table>
      <div v-else class="empty-state">
        Нет данных о пользователях
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * Пользователи системы: список и смена роли (GET/PATCH /admin/users).
 * Собственную роль менять нельзя — backend отвечает 400, а выбор заблокирован и
 * на клиенте: администратор без роли потерял бы доступ к панели.
 */
import { computed, onMounted, ref } from 'vue'
import { useAuth } from '~/composables/useAuth'
import type { UserRole } from '~/composables/useAuth'

definePageMeta({ layout: 'workspace' })

/** Ответ backend: app/schemas/user.py (UserResponse). */
interface AdminUser {
  id: string
  email: string
  role: UserRole
  created_at: string
}

const { user: currentUser } = useAuth()
const { $api } = useNuxtApp() as any
const toast = useToast()

const users = ref<AdminUser[]>([])
const isLoading = ref(false)
const busyIds = ref<string[]>([])
/** Скелетон вместо пустого состояния — только на первой загрузке страницы. */
const showSkeleton = computed(() => isLoading.value && users.value.length === 0)

const currentUserId = computed(() => currentUser.value?.id ?? '')

function isBusy(user: AdminUser) {
  return busyIds.value.includes(user.id)
}

function formatDate(value: string) {
  return new Date(value).toLocaleDateString('ru-RU')
}

async function loadUsers() {
  isLoading.value = true
  try {
    const response = await $api('/admin/users')
    users.value = response.users
  } catch (err: any) {
    toast.fromError(err, 'Не удалось загрузить список пользователей')
  } finally {
    isLoading.value = false
  }
}

async function updateRole(user: AdminUser) {
  busyIds.value = [...busyIds.value, user.id]
  try {
    const updated = await $api(`/admin/users/${user.id}`, {
      method: 'PATCH',
      body: { role: user.role },
    })
    user.role = updated.role
    toast.success('Роль обновлена')
  } catch (err: any) {
    toast.fromError(err, 'Не удалось изменить роль')
    await loadUsers()
  } finally {
    busyIds.value = busyIds.value.filter((id) => id !== user.id)
  }
}

onMounted(loadUsers)
</script>
