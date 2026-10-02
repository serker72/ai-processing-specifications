<template>
  <div class="page-container">
    <h1>Системные настройки</h1>

    <div class="upload-section">
      <h3>Реквизиты продавца</h3>
      <div class="upload-form sm:grid-cols-2">
        <div class="form-group col-span-full">
          <label for="seller-name">Наименование</label>
          <input id="seller-name" v-model="form.seller_name" class="form-control" type="text" />
        </div>
        <div class="form-group">
          <label for="seller-inn">ИНН</label>
          <input id="seller-inn" v-model="form.seller_inn" class="form-control" type="text" />
        </div>
        <div class="form-group">
          <label for="seller-kpp">КПП</label>
          <input id="seller-kpp" v-model="form.seller_kpp" class="form-control" type="text" />
        </div>
        <div class="form-group col-span-full">
          <label for="seller-address">Юридический адрес</label>
          <input id="seller-address" v-model="form.seller_address" class="form-control" type="text" />
        </div>
        <div class="form-group">
          <label for="seller-phone">Телефон</label>
          <input id="seller-phone" v-model="form.seller_phone" class="form-control" type="text" />
        </div>
        <div class="form-group">
          <label for="seller-email">Email</label>
          <input id="seller-email" v-model="form.seller_email" class="form-control" type="email" />
        </div>
        <div class="form-group">
          <label for="bank-account">Расчётный счёт</label>
          <input id="bank-account" v-model="form.bank_account" class="form-control" type="text" />
        </div>
        <div class="form-group">
          <label for="bank-name">Банк</label>
          <input id="bank-name" v-model="form.bank_name" class="form-control" type="text" />
        </div>
        <div class="form-group">
          <label for="bank-bik">БИК</label>
          <input id="bank-bik" v-model="form.bank_bik" class="form-control" type="text" />
        </div>
        <div class="form-group">
          <label for="corr-account">Корр. счёт</label>
          <input id="corr-account" v-model="form.corr_account" class="form-control" type="text" />
        </div>
        <div class="form-group">
          <label for="signer-name">ФИО подписанта</label>
          <input id="signer-name" v-model="form.signer_name" class="form-control" type="text" />
        </div>
        <div class="form-group">
          <label for="signer-position">Должность подписанта</label>
          <input id="signer-position" v-model="form.signer_position" class="form-control" type="text" />
        </div>
      </div>
    </div>

    <div class="upload-section">
      <h3>НДС</h3>
      <div class="upload-form sm:grid-cols-2">
        <div class="form-group">
          <label for="vat-rate">Ставка НДС, %</label>
          <input
            id="vat-rate"
            v-model.number="form.vat_rate"
            class="form-control"
            type="number"
            min="0"
            max="100"
            step="0.01"
          />
        </div>
        <div class="form-group">
          <label for="vat-included">НДС выделять из цены</label>
          <label class="checkbox-row">
            <input id="vat-included" v-model="form.vat_included" type="checkbox" />
            <span>
              Цены указаны с НДС (в итоге — строка «В том числе НДС»); иначе НДС
              начисляется сверху и выводится «Без НДС» / «Всего»
            </span>
          </label>
        </div>
      </div>
    </div>

    <div class="form-actions">
      <button class="btn-upload" :disabled="isSaving" @click="save">
        {{ isSaving ? 'Сохранение…' : 'Сохранить' }}
      </button>
    </div>

    <p v-if="error" class="text-danger">{{ error }}</p>
    <p v-if="saved" class="text-muted">Настройки сохранены</p>
  </div>
</template>

<script setup lang="ts">
/**
 * Системные настройки: реквизиты продавца и параметры НДС (singleton).
 * GET/PATCH /admin/settings (app/schemas/app_settings.py).
 */
import { onMounted, ref } from 'vue'

definePageMeta({ layout: 'workspace' })

interface AppSettings {
  seller_name: string | null
  seller_inn: string | null
  seller_kpp: string | null
  seller_address: string | null
  seller_phone: string | null
  seller_email: string | null
  bank_account: string | null
  bank_name: string | null
  bank_bik: string | null
  corr_account: string | null
  signer_name: string | null
  signer_position: string | null
  vat_rate: number
  vat_included: boolean
}

const { $api } = useNuxtApp() as any

const form = ref<AppSettings>({
  seller_name: '',
  seller_inn: '',
  seller_kpp: '',
  seller_address: '',
  seller_phone: '',
  seller_email: '',
  bank_account: '',
  bank_name: '',
  bank_bik: '',
  corr_account: '',
  signer_name: '',
  signer_position: '',
  vat_rate: 20,
  vat_included: false,
})

const isLoading = ref(false)
const isSaving = ref(false)
const error = ref('')
const saved = ref(false)

async function loadSettings() {
  isLoading.value = true
  error.value = ''
  try {
    const response = await $api('/admin/settings')
    form.value = { ...form.value, ...response }
  } catch (err: any) {
    error.value = err?.data?.detail || 'Не удалось загрузить настройки'
  } finally {
    isLoading.value = false
  }
}

async function save() {
  isSaving.value = true
  error.value = ''
  saved.value = false
  try {
    const response = await $api('/admin/settings', { method: 'PATCH', body: form.value })
    form.value = { ...form.value, ...response }
    saved.value = true
  } catch (err: any) {
    error.value = err?.data?.detail || 'Не удалось сохранить настройки'
  } finally {
    isSaving.value = false
  }
}

onMounted(loadSettings)
</script>

<style scoped>
.checkbox-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 0.875rem;
  line-height: 1.4;
}
</style>
