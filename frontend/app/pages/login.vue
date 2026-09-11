<template>
  <div class="card mx-auto mt-24 max-w-md">
    <h1>Вход в систему</h1>
    <form @submit.prevent="handleLogin">
      <div class="form-group">
        <label for="email">Email</label>
        <input
          id="email"
          v-model="email"
          type="email"
          placeholder="manager@example.com"
          required
        />
      </div>
      <div class="form-group">
        <label for="password">Пароль</label>
        <input
          id="password"
          v-model="password"
          type="password"
          placeholder="Secret123!"
          required
        />
      </div>
      <button type="submit" class="btn-submit w-full" :disabled="isLoading">
        {{ isLoading ? 'Вход...' : 'Войти' }}
      </button>
      <p v-if="error" class="text-danger mt-2">{{ error }}</p>
      <p v-if="fingerprintStatus === 'loading'" class="text-muted mt-2 italic">Генерация fingerprint...</p>
      <p v-if="fingerprintError" class="text-danger mt-2">{{ fingerprintError.message }}</p>
    </form>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useFingerprint } from '~/composables/useFingerprint'
import { useAuth } from '~/composables/useAuth'

const email = ref('')
const password = ref('')
const { login, isLoading, error } = useAuth()

// Fingerprint генерирует ThumbmarkJS (client-only плагин), храним его в плагине
const { isLoading: fpLoading, error: fingerprintError, init } = useFingerprint()
const fingerprintStatus = computed(() => (fpLoading.value ? 'loading' : 'ready'))

async function handleLogin() {
  // Дожидаемся отпечатка: запрос с пустым fingerprint backend отклонит с 422
  const fingerprint = await init()
  if (!fingerprint) {
    return
  }

  const result = await login(email.value, password.value, fingerprint)

  if (result.success) {
    // Перенаправляем на страницу спецификаций
    navigateTo('/manager/specifications')
  }
}
</script>
