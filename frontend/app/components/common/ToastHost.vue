<template>
  <!-- Хост тостов: один на приложение, подключается в layout'ах. aria-live
       объявляет сообщения скринридерам, клик по тосту закрывает его. -->
  <div class="toast-host" aria-live="polite">
    <TransitionGroup name="toast">
      <div
        v-for="toast in toasts"
        :key="toast.id"
        :class="['toast', `toast-${toast.type}`]"
        role="status"
        @click="dismiss(toast.id)"
      >
        <span class="toast-message">{{ toast.message }}</span>
        <button
          class="toast-close"
          type="button"
          aria-label="Закрыть уведомление"
          @click.stop="dismiss(toast.id)"
        >
          ×
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

<script setup lang="ts">
const { toasts, dismiss } = useToast()
</script>
