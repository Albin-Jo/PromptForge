import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { ApiError } from "../lib/api";
import { renderVersion, usePrompt } from "../lib/prompts/api";
import { streamCompletion, type CompletionConfig } from "../lib/streaming";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Skeleton } from "../components/ui/skeleton";
import { Textarea } from "../components/ui/textarea";
import { toast } from "../lib/toast";

type RunStatus = "idle" | "rendering" | "streaming" | "done" | "error";

function messageFor(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 422) return `Could not render: ${err.message}`;
    return err.message;
  }
  return "Something went wrong. Is the API reachable?";
}

export function PlaygroundPage() {
  const { name, versionNumber } = useParams();
  const version_number = Number(versionNumber);
  const { data: prompt, isPending, isError, error } = usePrompt(name);

  const version = useMemo(
    () => prompt?.versions.find((v) => v.version_number === version_number),
    [prompt, version_number],
  );

  // Variable values keyed by the version's declared input_variables.
  const [variables, setVariables] = useState<Record<string, string>>({});

  // The model to call; prefilled from the version's saved config, then editable here.
  const savedModel = (version?.model_settings?.model as string | undefined) ?? "";
  const [model, setModel] = useState("");
  // Prefill once the saved model is known. Keyed on the string (not the version object)
  // so a background refetch returning the same model doesn't clobber the user's edit.
  useEffect(() => {
    if (savedModel) setModel(savedModel);
  }, [savedModel]);

  const [output, setOutput] = useState("");
  const [status, setStatus] = useState<RunStatus>("idle");
  const [runError, setRunError] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  if (isPending) {
    return (
      <div role="status" aria-label="Loading prompt…" className="max-w-md space-y-3">
        <Skeleton className="h-6 w-1/2" />
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-20 w-full" />
      </div>
    );
  }
  if (isError) {
    return <p className="text-sm text-destructive">Could not load prompt: {error.message}</p>;
  }
  if (!version) {
    return <p className="text-sm text-destructive">No version v{versionNumber} for {name}.</p>;
  }

  const busy = status === "rendering" || status === "streaming";

  async function run() {
    if (!name) return;
    setRunError(null);
    setOutput("");
    setStatus("rendering");

    const controller = new AbortController();
    controllerRef.current = controller;

    let rendered;
    try {
      rendered = await renderVersion(name, version_number, variables);
    } catch (err) {
      const message = messageFor(err);
      setRunError(message);
      setStatus("error");
      toast.error(message);
      return;
    }

    // The version's saved settings are the call's config; the model field overrides `model`.
    // This is an unchecked boundary cast: model_settings is a free JSONB bag, so a bad
    // field here surfaces as a 422 from /complete (shown as a stream error), not a type error.
    const config = {
      ...(rendered.model_settings ?? {}),
      model: model.trim(),
    } as CompletionConfig;

    setStatus("streaming");
    await streamCompletion(
      { messages: [{ role: "user", content: rendered.prompt }], config },
      {
        onToken: (content) => setOutput((prev) => prev + content),
        onDone: () => setStatus("done"),
        onError: (detail) => {
          setRunError(detail);
          setStatus("error");
          toast.error(detail);
        },
      },
      controller.signal,
    );
  }

  function stop() {
    controllerRef.current?.abort();
    setStatus("idle");
  }

  return (
    <div>
      {/* Back-to-versions navigation is the breadcrumb's job now (the prompt-name crumb links
          to .../versions), so the header is just the title. */}
      <h1 className="text-xl font-semibold">
        Playground — {name} <span className="text-muted-foreground">v{version_number}</span>
      </h1>

      <div className="mt-6 grid grid-cols-1 gap-6 md:grid-cols-2">
        <div>
          <h2 className="text-sm font-medium text-foreground">Inputs</h2>

          <label className="mt-3 block text-sm text-muted-foreground">
            Model
            <Input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="openai/gpt-4o-mini"
              className="mt-1"
            />
          </label>

          {version.input_variables.length === 0 ? (
            <p className="mt-3 text-sm text-muted-foreground">This version takes no variables.</p>
          ) : (
            version.input_variables.map((varName) => (
              <label key={varName} className="mt-3 block text-sm text-muted-foreground">
                {varName}
                <Textarea
                  rows={2}
                  value={variables[varName] ?? ""}
                  onChange={(e) =>
                    setVariables((prev) => ({ ...prev, [varName]: e.target.value }))
                  }
                  className="mt-1 font-mono"
                />
              </label>
            ))
          )}

          <div className="mt-4 flex items-center gap-2">
            <Button type="button" onClick={run} disabled={busy || model.trim() === ""}>
              {busy ? "Running…" : "Run"}
            </Button>
            {status === "streaming" && (
              <Button type="button" variant="outline" onClick={stop}>
                Stop
              </Button>
            )}
            <StatusBadge status={status} />
          </div>
        </div>

        <div>
          <h2 className="text-sm font-medium text-foreground">Output</h2>
          <pre
            aria-label="Completion output"
            className="mt-3 min-h-40 whitespace-pre-wrap break-words rounded-md border border-border bg-muted/40 p-3 font-mono text-sm text-foreground"
          >
            {output}
            {status === "streaming" && <span className="animate-pulse">▋</span>}
          </pre>
          {runError && <p className="mt-2 text-sm text-destructive">{runError}</p>}
        </div>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: RunStatus }) {
  if (status === "idle") return null;
  const text: Record<Exclude<RunStatus, "idle">, string> = {
    rendering: "Rendering…",
    streaming: "Streaming…",
    done: "Done",
    error: "Error",
  };
  const variant =
    status === "error" ? "destructive" : status === "done" ? "success" : "secondary";
  return <Badge variant={variant}>{text[status]}</Badge>;
}
