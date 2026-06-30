// Wire types for the LLM gateway's read endpoints (Sprint 28). Mirrors the API's
// `ModelsResponse` (api/src/promptforge_api/routers/gateway.py).

/** The model identifiers the gateway is configured to offer the playground picker. */
export interface ModelsResponse {
  models: string[];
}
