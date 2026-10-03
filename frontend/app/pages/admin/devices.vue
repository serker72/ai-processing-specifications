<template>
  <div class="page-container">
    <h1>Устройства (fingerprint)</h1>

    <div class="mb-5">
      <button class="btn-secondary" :disabled="isLoading" @click="loadDevices">
        {{ isLoading ? 'Обновление...' : 'Обновить' }}
      </button>
    </div>

    <div class="table-wrapper">
      <table v-if="devices.length || showSkeleton" class="data-table">
        <thead>
          <tr>
            <th>Отпечаток устройства</th>
            <th>Первый вход</th>
            <th>Последний вход</th>
            <th>Статус</th>
            <th>Действия</th>
          </tr>
        </thead>
        <tbody>
          <template v-if="showSkeleton">
            <CommonTableSkeleton :columns="5" />
          </template>
          <template v-else>
            <tr v-for="device in devices" :key="device.fingerprint_hash">
              <td class="mono" :title="device.fingerprint_hash">
                {{ shortHash(device.fingerprint_hash) }}
              </td>
              <td>{{ formatDateTime(device.first_seen_at) }}</td>
              <td>{{ formatDateTime(device.last_seen_at) }}</td>
              <td>
                <span class="status-badge" :class="device.blocked ? 'blocked' : 'active'">
                  {{ device.blocked ? 'Заблокировано' : 'Разрешено' }}
                </span>
              </td>
              <td>
                <button
                  :class="device.blocked ? 'btn-unblock' : 'btn-block'"
                  :disabled="busyHashes.includes(device.fingerprint_hash)"
                  @click="toggleBlock(device)"
                >
                  {{ device.blocked ? 'Разблокировать' : 'Заблокировать' }}
                </button>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
      <div v-else class="empty-state">
        Устройства ещё не регистрировались
      </div>
    </div>

    <p class="text-xs text-muted mt-4">
      Блокировка запрещает вход с устройства и сразу отзывыает его активные сессии.
    </p>
  </div>
</template>

<script setup lang="ts">
/**
 * Реестр fingerprint-устройств и блокировка входа (GET/PATCH /admin/devices).
 * Хранится только SHA-256 отпечатка — сами отпечатки на сервер не попадают.
 */
import { onMounted, ref } from 'vue'

definePageMeta({ layout: 'workspace' })

/** Ответ backend: app/schemas/device.py (DeviceItem). */
interface DeviceItem {
  fingerprint_hash: string
  blocked: boolean
  first_seen_at: string
  last_seen_at: string
}

const { $api } = useNuxtApp() as any
const toast = useToast()

const devices = ref<DeviceItem[]>([])
const isLoading = ref(false)
const busyHashes = ref<string[]>([])
/** Скелетон вместо пустого состояния — только на первой загрузке страницы. */
const showSkeleton = computed(() => isLoading.value && devices.value.length === 0)

function shortHash(hash: string) {
  return `${hash.slice(0, 12)}…${hash.slice(-4)}`
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString('ru-RU')
}

async function loadDevices() {
  isLoading.value = true
  try {
    const response = await $api('/admin/devices')
    devices.value = response.devices
  } catch (err: any) {
    toast.fromError(err, 'Не удалось загрузить список устройств')
  } finally {
    isLoading.value = false
  }
}

async function toggleBlock(device: DeviceItem) {
  const blocked = !device.blocked
  busyHashes.value = [...busyHashes.value, device.fingerprint_hash]
  try {
    const updated = await $api(`/admin/devices/${device.fingerprint_hash}`, {
      method: 'PATCH',
      body: { blocked },
    })
    device.blocked = updated.blocked
    toast.success(blocked ? 'Устройство заблокировано' : 'Устройство разблокировано')
  } catch (err: any) {
    toast.fromError(err, 'Не удалось изменить статус устройства')
  } finally {
    busyHashes.value = busyHashes.value.filter((hash) => hash !== device.fingerprint_hash)
  }
}

onMounted(loadDevices)
</script>
