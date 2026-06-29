import { useState } from "react";
import type { FormEvent } from "react";
import { CompositionEditor } from "./CompositionEditor";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Textarea } from "./ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./ui/select";
import { parseVariables } from "../lib/utils";
import type { BlockRef } from "../lib/prompts/types";
import type { BlockRole } from "../lib/blocks/types";

export interface BlockFormValues {
  name: string;
  role: BlockRole;
  description: string;
  content: string;
  inputVariables: string[];
  blocks: BlockRef[];
}

interface BlockEditorFormProps {
  // "create" sets block identity (name/role/description); "version" appends an immutable version, so
  // only the body is editable — name/role/description live on the block and have no edit endpoint.
  mode: "create" | "version";
  initial: {
    name: string;
    role: BlockRole;
    description: string;
    content: string;
    inputVariables: string[];
  };
  blocks?: BlockRef[];
  submitting: boolean;
  errorMessage: string | null;
  onSubmit: (values: BlockFormValues) => void;
}

const ROLES: { value: BlockRole; label: string }[] = [
  { value: "role", label: "Role" },
  { value: "context", label: "Context" },
  { value: "guardrails", label: "Guardrails" },
  { value: "output_format", label: "Output format" },
  { value: "other", label: "Other" },
];

export function BlockEditorForm({
  mode,
  initial,
  blocks = [],
  submitting,
  errorMessage,
  onSubmit,
}: BlockEditorFormProps) {
  const [name, setName] = useState(initial.name);
  const [role, setRole] = useState<BlockRole>(initial.role);
  const [description, setDescription] = useState(initial.description);
  const [content, setContent] = useState(initial.content);
  const [variables, setVariables] = useState(initial.inputVariables.join(", "));
  const [composition, setComposition] = useState<BlockRef[]>(blocks);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    onSubmit({
      name: name.trim(),
      role,
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
              placeholder="safety-guardrails"
              className="mt-1"
            />
          </label>

          <div className="mt-4 text-sm font-medium text-foreground">
            Role
            <Select value={role} onValueChange={(v) => setRole(v as BlockRole)}>
              <SelectTrigger className="mt-1 w-56" aria-label="Role">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ROLES.map((r) => (
                  <SelectItem key={r.value} value={r.value}>
                    {r.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <label className="mt-4 block text-sm font-medium text-foreground">
            Description
            <Input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What this block contributes"
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
          placeholder={"Always answer in {{tone}}."}
          className="mt-1 font-mono"
        />
      </label>

      <label className="mt-4 block text-sm font-medium text-foreground">
        Input variables
        <Input
          type="text"
          value={variables}
          onChange={(e) => setVariables(e.target.value)}
          placeholder="tone"
          className="mt-1"
        />
      </label>
      <p className="mt-1 text-xs text-muted-foreground">
        Comma-separated. Must match the {"{{placeholders}}"} in the content (plus any from composed
        blocks).
      </p>

      <CompositionEditor value={composition} onChange={setComposition} />

      {errorMessage && <p className="mt-4 text-sm text-destructive">{errorMessage}</p>}

      <Button type="submit" disabled={submitting} className="mt-6">
        {submitting ? "Saving…" : mode === "create" ? "Create block" : "Save new version"}
      </Button>
    </form>
  );
}
