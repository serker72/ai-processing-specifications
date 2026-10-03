<template>
  <div class="page-container">
    <h1>Активные сессии</h1>

    <div class="mb-5">
      <button class="btn-secondary" :disabled="isLoading" @click="loadSessions">
        {{ isLoading ? 'Обновление...' : 'Обновить' }}
      </button>
    </div>

    <div class="table-wrapper">
      <table v-if="sessions.length || showSkeleton" class="data-table">
        <thead>
          <tr>
            <th>Пользователь</th>
            <th>Отпечаток устройства</th>
            <th>Доступен до</th>
            <th>Действия</th>
          </tr>
        </thead>
        <tbody>
          <template v-if="showSkeleton">
            <CommonTableSkeleton :columns="4" />
          </template>
          <template v-else>
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
          </template>
        </tbody>
      </table>
      <div v-else class="empty-state">
        Активных сессий нет
      </div>
    </div>

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
const toast = useToast()

const sessions = ref<SessionRow[]>([])
const isLoading = ref(false)
const busyKeys = ref<string[]>([])
/** Скелетон вместо пустого состояния — только на первой загрузке страницы. */
const showSkeleton = computed(() => isLoading.value && sessions.value.length === 0)

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
  try {
    const response = await $api('/admin/sessions')
    sessions.value = response.sessions
  } catch (err: any) {
    toast.fromError(err, 'Не удалось загрузить список сессий')
  } finally {
    isLoading.value = false
  }
}

async function revoke(session: SessionRow) {
  const key = rowKey(session)
  busyKeys.value = [...busyKeys.value, key]
  try {
    await $api(`/admin/sessions/${session.user_id}/${session.fingerprint_hash}`, {
      method: 'DELETE',
    })
    sessions.value = sessions.value.filter((item) => rowKey(item) !== key)
    toast.success('Сессия отозвана')
  } catch (err: any) {
    toast.fromError(err, 'Не удалось отозвать сессию')
  } finally {
    busyKeys.value = busyKeys.value.filter((item) => item !== key)
  }
}

onMounted(loadSessions)
</script>
