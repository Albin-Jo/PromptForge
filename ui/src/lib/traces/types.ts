// Mirrors the API's TraceSummary / TraceDetail (api/.../schemas.py).
//
// A trace is one model execution linked back to the prompt version that produced it. The list
// shows the lean summary (cost/latency/status/model); the drill-down fetches the full detail,
// which adds the rendered prompt (`input`), the model `output`, token counts, and error info.

// A model execution's outcome — mirrors the traces.status CHECK ('ok' | 'error').
export type TraceStatus = "ok" | "error";

// Mirrors TraceSummary — one row in the trace list (no rendered prompt/output).
// `cost_usd` is an exact decimal string from the API (never parsed to a float for arithmetic).
export interface TraceSummary {
  id: string;
  prompt_id: string | null;
  prompt_version_id: string | null;
  source: string | null;
  provider: string | null;
  model: string;
  cost_usd: string | null;
  latency_ms: number | null;
  status: TraceStatus;
  created_at: string;
}

// Mirrors TraceDetail — one execution in full, for the debugging drill-down.
export interface TraceDetail extends TraceSummary {
  provider_model: string | null;
  request_id: string | null;
  input: string | null;
  output: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  error_type: string | null;
}
