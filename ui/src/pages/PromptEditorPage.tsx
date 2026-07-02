import { useNavigate, useParams } from "react-router-dom";
import { ApiError } from "../lib/api";
import { useCreatePrompt, useCreateVersion, usePrompt } from "../lib/prompts/api";
import type { PromptVersion } from "../lib/prompts/types";
import { PromptEditorForm } from "../components/PromptEditorForm";
import type { PromptFormValues } from "../components/PromptEditorForm";
import { PromptTabs } from "../components/PromptTabs";
import { GoldenSetSelect } from "../components/GoldenSetSelect";
import { toast } from "../lib/toast";

function messageFor(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 409) return "A prompt with that name already exists.";
    if (err.status === 422) return `Validation failed: ${err.message}`;
    return err.message;
  }
  return "Something went wrong. Is the API reachable?";
}

export function PromptEditorPage() {
  const { name } = useParams();
  const navigate = useNavigate();
  const isEdit = Boolean(name);

  // Edit mode loads the prompt so we can pre-fill from, and carry forward, its latest version.
  const promptQuery = usePrompt(name);
  const createPrompt = useCreatePrompt();
  const createVersion = useCreateVersion(name ?? "");

  if (isEdit && promptQuery.isPending) {
    return <p className="text-sm text-muted-foreground">Loading prompt…</p>;
  }
  if (isEdit && promptQuery.isError) {
    return (
      <p className="text-sm text-destructive">
        Could not load prompt: {promptQuery.error.message}
      </p>
    );
  }

  // Versions come oldest-first; the latest is the editing starting point.
  const versions = promptQuery.data?.versions ?? [];
  const latest: PromptVersion | undefined = versions[versions.length - 1];

  const initial = {
    name: name ?? "",
    description: promptQuery.data?.description ?? "",
    content: latest?.content ?? "",
    inputVariables: latest?.input_variables ?? [],
  };

  function handleSubmit(values: PromptFormValues) {
    if (isEdit && name) {
      // model_settings / output_schema carry forward unchanged; blocks now come from the
      // composition editor (Sprint 15, Task 2) rather than being carried forward as-is.
      createVersion.mutate(
        {
          content: values.content,
          input_variables: values.inputVariables,
          model_settings: latest?.model_settings ?? null,
          output_schema: latest?.output_schema ?? null,
          blocks: values.blocks,
        },
        {
          onSuccess: (version) => {
            toast.success(`Saved ${name} v${version.version_number}`);
            navigate("/prompts");
          },
          onError: (err) => toast.error(messageFor(err)),
        },
      );
    } else {
      createPrompt.mutate(
        {
          name: values.name,
          description: values.description || null,
          content: values.content,
          input_variables: values.inputVariables,
          blocks: values.blocks,
        },
        {
          onSuccess: (prompt) => {
            toast.success(`Created prompt “${prompt.name}”`);
            navigate("/prompts");
          },
          onError: (err) => toast.error(messageFor(err)),
        },
      );
    }
  }

  const mutation = isEdit ? createVersion : createPrompt;

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">{isEdit ? `Edit: ${name}` : "New prompt"}</h1>
      {isEdit && name && (
        <div className="mt-4">
          <PromptTabs name={name} />
        </div>
      )}
      <p className="mt-1 text-sm text-muted-foreground">
        {isEdit
          ? "Saving creates a new immutable version."
          : "Create a prompt and its first version."}
      </p>

      <div className="mt-6">
        <PromptEditorForm
          mode={isEdit ? "edit" : "create"}
          initial={initial}
          blocks={isEdit ? latest?.blocks : undefined}
          submitting={mutation.isPending}
          errorMessage={mutation.isError ? messageFor(mutation.error) : null}
          onSubmit={handleSubmit}
        />
      </div>

      {/* The promotion gate is a property of the prompt, not a version — only meaningful once the
          prompt exists, so it's shown on edit, below the version form. */}
      {isEdit && name && (
        <GoldenSetSelect promptName={name} attachedId={promptQuery.data?.golden_set_id ?? null} />
      )}
    </div>
  );
}
