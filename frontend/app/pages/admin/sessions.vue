<template>
  <div class="page-container">
    <h1>Управление сессиями</h1>
    
    <div class="table-wrapper overflow-x-auto">
      <table class="data-table">
        <thead>
          <tr>
            <th>User ID</th>
            <th>Fingerprint</th>
            <th>IP Address</th>
            <th>Создана</th>
            <th>Истекает</th>
            <th>Действия</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="session in sessions" :key="session.id">
            <td>{{ session.user_id }}</td>
            <td class="mono">{{ session.fingerprint }}</td>
            <td>{{ session.ip_address }}</td>
            <td>{{ new Date(session.created_at).toLocaleString() }}</td>
            <td>{{ new Date(session.expires_at).toLocaleString() }}</td>
            <td>
              <button class="btn-revoke" @click="revokeSession(session.id)">Отозвать</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="!sessions.length" class="empty-state">
      Нет активных сессий
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

// Mock data for demonstration
const sessions = ref([
  { 
    id: 'sess-1', 
    user_id: '1dcf548d-4557-4d43-93a4-db033fa4718e', 
    fingerprint: '283628ad0c50441d9b93538c6ad99784fddbdce0fc2b96124c70cbf4b0789753', 
    ip_address: '127.0.0.1', 
    created_at: '2023-09-08T10:00:00Z', 
    expires_at: '2023-09-15T10:00:00Z' 
  },
  { 
    id: 'sess-2', 
    user_id: '2', 
    fingerprint: '57e19849a701070071cd3ee1231c5b5714cabaa9458ab16033a6e4f47bba932a', 
    ip_address: '192.168.1.10', 
    created_at: '2023-09-07T15:30:00Z', 
    expires_at: '2023-09-14T15:30:00Z' 
  },
])

async function revokeSession(sessionId: string) {
  if (confirm('Are you sure you want to revoke this session?')) {
    // TODO: Implement API call to revoke session
    console.log('Revoke session', sessionId)
    // Remove from local list for immediate feedback
    sessions.value = sessions.value.filter(s => s.id !== sessionId)
  }
}
</script>
