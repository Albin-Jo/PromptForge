/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  // Flower (the Celery operator dashboard) URL, linked from the admin Operations page. Optional;
  // defaults to the compose port (http://localhost:5555) when unset.
  readonly VITE_FLOWER_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
