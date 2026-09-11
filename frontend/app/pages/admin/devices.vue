<template>
  <div class="page-container">
    <h1>Управление устройствами</h1>
    
    <div class="table-wrapper overflow-x-auto">
      <table class="data-table">
        <thead>
          <tr>
            <th>Fingerprint</th>
            <th>Последняя активность</th>
            <th>Статус</th>
            <th>Действия</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="device in devices" :key="device.fingerprint">
            <td class="mono">{{ device.fingerprint }}</td>
            <td>{{ new Date(device.last_active).toLocaleString() }}</td>
            <td>
              <span :class="['status-badge', device.blocked ? 'blocked' : 'active']">
                {{ device.blocked ? 'Заблокировано' : 'Активно' }}
              </span>
            </td>
            <td>
              <button 
                class="btn-action" 
                :class="device.blocked ? 'btn-unblock' : 'btn-block'"
                @click="toggleBlockDevice(device)"
              >
                {{ device.blocked ? 'Разблокировать' : 'Заблокировать' }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="!devices.length" class="empty-state">
      Нет зарегистрированных устройств
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

// Mock data for demonstration
const devices = ref([
  { fingerprint: '283628ad0c50441d9b93538c6ad99784fddbdce0fc2b96124c70cbf4b0789753', last_active: '2023-09-08T10:00:00Z', blocked: false },
  { fingerprint: '57e19849a701070071cd3ee1231c5b5714cabaa9458ab16033a6e4f47bba932a', last_active: '2023-09-07T15:30:00Z', blocked: true },
])

async function toggleBlockDevice(device: any) {
  // TODO: Implement API call to block/unblock device
  device.blocked = !device.blocked
  console.log('Toggle block for', device.fingerprint, 'to', device.blocked)
}
</script>
