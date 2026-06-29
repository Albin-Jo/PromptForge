import { useState } from "react";
import type { FormEvent } from "react";
import { CompositionEditor } from "./CompositionEditor";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Textarea } from "./ui/textarea";
import { parseVariables } from "../lib/utils";
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

      <CompositionEditor value={composition} onChange={setComposition} />

      {errorMessage && <p className="mt-4 text-sm text-destructive">{errorMessage}</p>}

      <Button type="submit" disabled={submitting} className="mt-6">
        {submitting ? "Saving…" : mode === "create" ? "Create prompt" : "Save new version"}
      </Button>
    </form>
  );
}
