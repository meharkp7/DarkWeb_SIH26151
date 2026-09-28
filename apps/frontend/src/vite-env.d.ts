/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL for `/api/v1/*` routes. Defaults to `/api`. */
  readonly VITE_API_BASE?: string;
  /** Base URL for health probes. Defaults to `/health`. */
  readonly VITE_HEALTH_URL?: string;
}
