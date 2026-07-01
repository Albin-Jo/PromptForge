import { useNavigate, useParams } from "react-router-dom";
import { ApiError } from "../lib/api";
import { useBlock, useCreateBlock, useCreateBlockVersion } from "../lib/blocks/api";
import { BlockEditorForm } from "../components/BlockEditorForm";
import type { BlockFormValues } from "../components/BlockEditorForm";
import type { BlockVersion } from "../lib/blocks/types";
import { toast } from "../lib/toast";

function messageFor(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 409) return "A block with that name already exists.";
    if (err.status === 422) return `Validation failed: ${err.message}`;
    return err.message;
  }
  return "Something went wrong. Is the API reachable?";
}

export function BlockEditorPage() {
  const { name } = useParams();
  const navigate = useNavigate();
  const isVersion = Boolean(name);

  // New-version mode loads the block so we can carry forward its latest version as a starting point.
  const blockQuery = useBlock(name);
  const createBlock = useCreateBlock();
  const createVersion = useCreateBlockVersion(name ?? "");

  if (isVersion && blockQuery.isPending) {
    return <p className="text-sm text-muted-foreground">Loading block…</p>;
  }
  if (isVersion && blockQuery.isError) {
    return (
      <p className="text-sm text-destructive">Could not load block: {blockQuery.error.message}</p>
    );
  }

  const versions = blockQuery.data?.versions ?? [];
  const latest: BlockVersion | undefined = [...versions].sort(
    (a, b) => b.version_number - a.version_number,
  )[0];

  const initial = {
    name: name ?? "",
    role: blockQuery.data?.role ?? ("role" as const),
    description: blockQuery.data?.description ?? "",
    content: latest?.content ?? "",
    inputVariables: latest?.input_variables ?? [],
  };

  function handleSubmit(values: BlockFormValues) {
    if (isVersion && name) {
      createVersion.mutate(
        {
          content: values.content,
          input_variables: values.inputVariables,
          blocks: values.blocks,
        },
        {
          onSuccess: (version) => {
            toast.success(`Saved ${name} v${version.version_number}`);
            navigate(`/blocks/${encodeURIComponent(name)}`);
          },
          onError: (err) => toast.error(messageFor(err)),
        },
      );
    } else {
      createBlock.mutate(
        {
          name: values.name,
          role: values.role,
          description: values.description || null,
          content: values.content,
          input_variables: values.inputVariables,
          blocks: values.blocks,
        },
        {
          onSuccess: (block) => {
            toast.success(`Created block “${block.name}”`);
            navigate(`/blocks/${encodeURIComponent(block.name)}`);
          },
          onError: (err) => toast.error(messageFor(err)),
        },
      );
    }
  }

  const mutation = isVersion ? createVersion : createBlock;

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">{isVersion ? `New version: ${name}` : "New block"}</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        {isVersion
          ? "Saving creates a new immutable version of this block."
          : "Create a block and its first version. Blocks compose into prompts."}
      </p>

      <div className="mt-6">
        <BlockEditorForm
          mode={isVersion ? "version" : "create"}
          initial={initial}
          blocks={isVersion ? latest?.blocks : undefined}
          submitting={mutation.isPending}
          errorMessage={mutation.isError ? messageFor(mutation.error) : null}
          onSubmit={handleSubmit}
        />
      </div>
    </div>
  );
}
