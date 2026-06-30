import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import { CompositionEditor } from "./CompositionEditor";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Textarea } from "./ui/textarea";
import { parseVariables } from "../lib/utils";
import { checkVariableContract } from "../lib/prompts/variables";
import { useBlocks } from "../lib/blocks/api";
import type { BlockRef } from "../lib/prompts/types";

export interface PromptFormValues {
  name: string;
  description: string;
  content: string;
  inputVariables: string[];
  blocks: BlockRef[];
}

interface PromptEditorFormProps {
  mode: "create" | "edit";
  initial: {
    name: string;
    description: string;
    content: string;
    inputVariables: string[];
  };
  /** Composition to start from (carried forward on edit); now editable in-place. */
  blocks?: BlockRef[];
  submitting: boolean;
  errorMessage: string | null;
  onSubmit: (values: PromptFormValues) => void;
}

export function PromptEditorForm({
  mode,
  initial,
  blocks = [],
  submitting,
  errorMessage,
  onSubmit,
}: PromptEditorFormProps) {
  const [name, setName] = useState(initial.name);
  const [description, setDescription] = useState(initial.description);
  const [content, setContent] = useState(initial.content);
  const [variables, setVariables] = useState(initial.inputVariables.join(", "));
  const [composition, setComposition] = useState<BlockRef[]>(blocks);

  // Block catalog (shared cache with CompositionEditor's useBlocks — one fetch, two readers).
  // We need the pinned versions' own input_variables to know what the composition contributes.
  const { data: catalog } = useBlocks();

  // Until the catalog loads, a composed prompt's contributed variables are unknown — so an
  // "unused" finding is premature and we shouldn't even show it. (Body-driven "undeclared" is
  // always valid: body placeholders are required regardless of any blocks.)
  const blocksKnown = composition.length === 0 || catalog !== undefined;

  // Union of the variables each composed block contributes, plus whether we could resolve
  // every block: an unresolved block (deleted/renamed) means our "required" set is undercounted,
  // so we must not hard-block Save on an "unused" finding we can't trust.
  const { blockVariables, allBlocksResolved } = useMemo(() => {
    const vars = new Set<string>();
    let resolved = true;
    for (const ref of composition) {
      const block = catalog?.find((b) => b.name === ref.block);
      const version = block?.versions.find((v) => v.version_number === ref.version);
      if (!version) {
        resolved = false;
        continue;
      }
      for (const v of version.input_variables) vars.add(v);
    }
    return { blockVariables: [...vars], allBlocksResolved: resolved };
  }, [composition, catalog]);

  // Live declared-vs-required diff, recomputed as the body, variables field, or blocks change.
  const declared = useMemo(() => parseVariables(variables), [variables]);
  const contract = useMemo(
    () => checkVariableContract(content, declared, blockVariables),
    [content, declared, blockVariables],
  );

  const hasUndeclared = contract.undeclared.length > 0;
  const hasUnused = blocksKnown && contract.unused.length > 0;
  // Hard-block only what we're certain about: undeclared placeholders are always a 422,
  // and unused declarations are too — but only trust "unused" when every block resolved.
  const saveBlocked = hasUndeclared || (hasUnused && allBlocksResolved);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    onSubmit({
      name: name.trim(),
      description: description.trim(),
      content,
      inputVariables: parseVariables(variables),
      blocks: composition,
    });
  }

  return (
    <form onSubmit={handleSubmit} className="max-w-2xl">
      {mode === "create" && (
        <>
          <label className="block text-sm font-medium text-foreground">
            Name
            <Input
              type="text"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="summarize-article"
              className="mt-1"
            />
          </label>

          <label className="mt-4 block text-sm font-medium text-foreground">
            Description
            <Input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What this prompt is for"
              className="mt-1"
            />
          </label>
        </>
      )}

      <label className="mt-4 block text-sm font-medium text-foreground">
        Content
        <Textarea
          required
          rows={10}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder={"Summarize the following:\n{{text}}"}
          className="mt-1 font-mono"
        />
      </label>

      <div className="mt-2 flex flex-wrap items-center gap-1.5" aria-live="polite">
        <span className="text-xs text-muted-foreground">Detected variables:</span>
        {contract.detected.length === 0 ? (
          <span className="text-xs text-muted-foreground">none yet</span>
        ) : (
          contract.detected.map((name) => (
            <Badge key={name} variant="secondary" className="font-mono text-xs">
              {`{{${name}}}`}
            </Badge>
          ))
        )}
      </div>

      <label className="mt-4 block text-sm font-medium text-foreground">
        Input variables
        <Input
          type="text"
          value={variables}
          onChange={(e) => setVariables(e.target.value)}
          placeholder="text, tone"
          className="mt-1"
        />
      </label>
      <p className="mt-1 text-xs text-muted-foreground">
        Comma-separated. Must match the {"{{placeholders}}"} in the content (plus any from blocks).
      </p>

      {(hasUndeclared || hasUnused) && (
        <div
          role="status"
          className="mt-2 space-y-1 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-foreground"
        >
          {hasUndeclared && (
            <p>
              Used by the prompt or its blocks but not declared:{" "}
              <span className="font-mono font-medium">{contract.undeclared.join(", ")}</span>. Add
              them to Input variables.
            </p>
          )}
          {hasUnused &&
            (allBlocksResolved ? (
              <p>
                Declared but never used:{" "}
                <span className="font-mono font-medium">{contract.unused.join(", ")}</span>. Remove
                them or reference them in the content.
              </p>
            ) : (
              <p>
                Possibly unused:{" "}
                <span className="font-mono font-medium">{contract.unused.join(", ")}</span> — a
                composed block couldn&apos;t be resolved, so this may be a false alarm.
              </p>
            ))}
        </div>
      )}

      <CompositionEditor value={composition} onChange={setComposition} />

      {errorMessage && <p role="alert" className="mt-4 text-sm text-destructive">{errorMessage}</p>}

      <Button
        type="submit"
        disabled={submitting || saveBlocked}
        title={saveBlocked ? "Resolve the variable mismatch above before saving." : undefined}
        className="mt-6"
      >
        {submitting ? "Saving…" : mode === "create" ? "Create prompt" : "Save new version"}
      </Button>
    </form>
  );
}
