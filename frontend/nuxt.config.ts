import tailwindcss from '@tailwindcss/vite'

// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  compatibilityDate: '2025-01-01',
  devtools: { enabled: true },
  ssr: true,
  css: ['~/assets/css/main.css'],
  modules: [],
  srcDir: 'app/',
  vite: {
    plugins: [tailwindcss()],
  },
  app: {
    head: {
      htmlAttrs: { lang: 'ru' },
      title: 'AI Processing Specifications',
      meta: [{ name: 'viewport', content: 'width=device-width, initial-scale=1' }],
      script: [
        {
          // Блокирующий скрипт до отрисовки: включает сохранённую тему на <html>
          // раньше, чем выполнится гидратация, — иначе между SSR и клиентом мигает
          // светлая версия страницы (FOUC).
          innerHTML: `try{var k='app_theme',t=localStorage.getItem(k);if(t!=='dark'&&t!=='light'){t=window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}document.documentElement.classList.toggle('dark',t==='dark');document.documentElement.style.colorScheme=t}catch(e){}`,
          tagPosition: 'head',
        },
      ],
    },
  },
  runtimeConfig: {
    public: {
      apiBase: process.env.NUXT_PUBLIC_API_BASE
    }
  }
})
