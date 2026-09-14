<template>
  <div class="page-container">
    <h1>Управление пользователями</h1>

    <div class="mb-5">
      <button class="btn-secondary" :disabled="isLoading" @click="loadUsers">
        {{ isLoading ? 'Обновление...' : 'Обновить' }}
      </button>
    </div>

    <div class="table-wrapper">
      <table v-if="users.length" class="data-table">
        <thead>
          <tr>
            <th>Email</th>
            <th>Роль</th>
            <th>Дата создания</th>
          </tr>
        </thead>
        <tbody>
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
        </tbody>
      </table>
      <div v-else class="empty-state">
        {{ isLoading ? 'Загрузка списка…' : 'Нет данных о пользователях' }}
      </div>
    </div>

    <p v-if="error" class="text-danger">{{ error }}</p>
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

const users = ref<AdminUser[]>([])
const isLoading = ref(false)
const error = ref('')
const busyIds = ref<string[]>([])

const currentUserId = computed(() => currentUser.value?.id ?? '')

function isBusy(user: AdminUser) {
  return busyIds.value.includes(user.id)
}

function formatDate(value: string) {
  return new Date(value).toLocaleDateString('ru-RU')
}

async function loadUsers() {
  isLoading.value = true
  error.value = ''
  try {
    const response = await $api('/admin/users')
    users.value = response.users
  } catch (err: any) {
    error.value = err?.data?.detail || 'Не удалось загрузить список пользователей'
  } finally {
    isLoading.value = false
  }
}

async function updateRole(user: AdminUser) {
  busyIds.value = [...busyIds.value, user.id]
  error.value = ''
  try {
    const updated = await $api(`/admin/users/${user.id}`, {
      method: 'PATCH',
      body: { role: user.role },
    })
    user.role = updated.role
  } catch (err: any) {
    error.value = err?.data?.detail || 'Не удалось изменить роль'
    await loadUsers()
  } finally {
    busyIds.value = busyIds.value.filter((id) => id !== user.id)
  }
}

onMounted(loadUsers)
</script>
