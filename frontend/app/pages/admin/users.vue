<template>
  <div class="page-container">
    <h1>Управление пользователями</h1>
    
    <div class="table-wrapper">
      <table class="data-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Email</th>
            <th>Роль</th>
            <th>Дата создания</th>
            <th>Действия</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="user in users" :key="user.id">
            <td>{{ user.id }}</td>
            <td>{{ user.email }}</td>
            <td>
              <select v-model="user.role" @change="updateRole(user)">
                <option value="admin">Admin</option>
                <option value="manager">Manager</option>
              </select>
            </td>
            <td>{{ new Date(user.created_at).toLocaleDateString() }}</td>
            <td>
              <button class="btn-edit" @click="editUser(user)">Изменить</button>
              <button class="btn-delete" @click="deleteUser(user.id)">Удалить</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="!users.length" class="empty-state">
      Нет данных о пользователях
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

// Mock data for demonstration
const users = ref([
  { id: '1dcf548d-4557-4d43-93a4-db033fa4718e', email: 'admin@example.com', role: 'admin', created_at: '2023-01-01T00:00:00Z' },
  { id: '2', email: 'manager@example.com', role: 'manager', created_at: '2023-01-02T00:00:00Z' },
])

async function updateRole(user: any) {
  // TODO: Implement API call to update user role
  console.log('Update role for', user.email, 'to', user.role)
}

function editUser(user: any) {
  console.log('Edit user', user.id)
}

async function deleteUser(id: string) {
  if (confirm('Are you sure you want to delete this user?')) {
    // TODO: Implement API call to delete user
    console.log('Delete user', id)
  }
}
</script>
