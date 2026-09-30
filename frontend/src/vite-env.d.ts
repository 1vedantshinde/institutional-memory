/// <reference types="vite/client" />

// Keep in sync with .env.example
interface ImportMetaEnv {
  readonly VITE_CHAT_API_URL?: string
  readonly VITE_CORE_API_URL?: string
  readonly VITE_DEFAULT_DATASET_PATH?: string
  readonly VITE_DEFAULT_CONFIG_PATH?: string
  readonly VITE_USE_MOCKS?: string
  readonly VITE_ENABLE_PROPOSED?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
