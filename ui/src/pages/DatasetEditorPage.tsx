import { useNavigate, useParams } from "react-router-dom";
import { ApiError } from "../lib/api";
import { useCreateDataset, useDataset, useUpdateDataset } from "../lib/datasets/api";
import { DatasetEditorForm } from "../components/DatasetEditorForm";
import type { DatasetFormValues } from "../components/DatasetEditorForm";
import { toast } from "../lib/toast";

function messageFor(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 409) return "A golden set with that name already exists.";
    if (err.status === 422) return `Validation failed: ${err.message}`;
    return err.message;
  }
  return "Something went wrong. Is the API reachable?";
}

export function DatasetEditorPage() {
  const { name } = useParams();
  const navigate = useNavigate();
  const isEdit = Boolean(name);

  const datasetQuery = useDataset(name);
  const createDataset = useCreateDataset();
  const updateDataset = useUpdateDataset(name ?? "");

  if (isEdit && datasetQuery.isPending) {
    return <p className="text-sm text-muted-foreground">Loading golden set…</p>;
  }
  if (isEdit && datasetQuery.isError) {
    return (
      <p className="text-sm text-destructive">
        Could not load golden set: {datasetQuery.error.message}
      </p>
    );
  }

  const initial = {
    name: name ?? "",
    description: datasetQuery.data?.description ?? "",
    items: datasetQuery.data?.items ?? [],
  };

  function handleSubmit(values: DatasetFormValues) {
    if (isEdit && name) {
      updateDataset.mutate(
        { description: values.description || null, items: values.items },
        {
          onSuccess: () => {
            toast.success(`Saved “${name}”`);
            navigate("/datasets");
          },
          onError: (err) => toast.error(messageFor(err)),
        },
      );
    } else {
      createDataset.mutate(
        { name: values.name, description: values.description || null, items: values.items },
        {
          onSuccess: (dataset) => {
            toast.success(`Created golden set “${dataset.name}”`);
            navigate("/datasets");
          },
          onError: (err) => toast.error(messageFor(err)),
        },
      );
    }
  }

  const mutation = isEdit ? updateDataset : createDataset;

  return (
    <div>
      <h1 className="text-xl font-semibold">{isEdit ? `Edit: ${name}` : "New golden set"}</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        {isEdit
          ? "Saving replaces the set's cases with what's below."
          : "Create a golden set and its cases."}
      </p>

      <div className="mt-6">
        <DatasetEditorForm
          mode={isEdit ? "edit" : "create"}
          initial={initial}
          submitting={mutation.isPending}
          errorMessage={mutation.isError ? messageFor(mutation.error) : null}
          onSubmit={handleSubmit}
        />
      </div>
    </div>
  );
}
