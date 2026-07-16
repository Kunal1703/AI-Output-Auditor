/// <reference types="vite/client" />

/** Typed access to the VITE_ environment variables this app reads. */
interface ImportMetaEnv {
  /** Backend base URL. Defaults to '/api', proxied to the backend in dev. */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
