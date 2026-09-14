<template>
  <div class="page-container">
    <h1>Активные сессии</h1>

    <div class="mb-5">
      <button class="btn-secondary" :disabled="isLoading" @click="loadSessions">
        {{ isLoading ? 'Обновление...' : 'Обновить' }}
      </button>
    </div>

    <div class="table-wrapper">
      <table v-if="sessions.length" class="data-table">
        <thead>
          <tr>
            <th>Пользователь</th>
            <th>Отпечаток устройства</th>
            <th>Доступен до</th>
            <th>Действия</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="session in sessions" :key="rowKey(session)">
            <td>{{ session.email || session.user_id }}</td>
            <td class="mono" :title="session.fingerprint_hash">
              {{ shortHash(session.fingerprint_hash) }}
            </td>
            <td>{{ formatDateTime(session.expires_at) }}</td>
            <td>
              <button
                class="btn-revoke"
                :disabled="busyKeys.includes(rowKey(session))"
                @click="revoke(session)"
              >
                Отозвать
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty-state">
        {{ isLoading ? 'Загрузка списка…' : 'Активных сессий нет' }}
      </div>
    </div>

    <p v-if="error" class="text-danger">{{ error }}</p>
    <p class="text-muted text-sm mt-4">
      Доступен refresh-токен сессии: после отзыва обновить токены не получится,
      а текущий access-токен доживёт до конца своего короткого срока.
    </p>
  </div>
</template>

<script setup lang="ts">
/**
 * Активные сессии (GET/DELETE /admin/sessions): список читается из Redis,
 * отзыв удаляет ключ сессии и отправляет jti refresh-токена в blacklist.
 */
import { onMounted, ref } from 'vue'

definePageMeta({ layout: 'workspace' })

/** Ответ backend: app/schemas/session.py (SessionItem). */
interface SessionRow {
  user_id: string
  email: string
  fingerprint_hash: string
  expires_at: string
}

const { $api } = useNuxtApp() as any

const sessions = ref<SessionRow[]>([])
const isLoading = ref(false)
const error = ref('')
const busyKeys = ref<string[]>([])

function rowKey(session: SessionRow) {
  return `${session.user_id}:${session.fingerprint_hash}`
}

function shortHash(hash: string) {
  return `${hash.slice(0, 12)}…${hash.slice(-4)}`
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString('ru-RU')
}

async function loadSessions() {
  isLoading.value = true
  error.value = ''
  try {
    const response = await $api('/admin/sessions')
    sessions.value = response.sessions
  } catch (err: any) {
    error.value = err?.data?.detail || 'Не удалось загрузить список сессий'
  } finally {
    isLoading.value = false
  }
}

async function revoke(session: SessionRow) {
  const key = rowKey(session)
  busyKeys.value = [...busyKeys.value, key]
  error.value = ''
  try {
    await $api(`/admin/sessions/${session.user_id}/${session.fingerprint_hash}`, {
      method: 'DELETE',
    })
    sessions.value = sessions.value.filter((item) => rowKey(item) !== key)
  } catch (err: any) {
    error.value = err?.data?.detail || 'Не удалось отозвать сессию'
  } finally {
    busyKeys.value = busyKeys.value.filter((item) => item !== key)
  }
}

onMounted(loadSessions)
</script>
