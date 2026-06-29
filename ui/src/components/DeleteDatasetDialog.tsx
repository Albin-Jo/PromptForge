import { useState } from "react";
import { ApiError } from "../lib/api";
import { useDeleteDataset } from "../lib/datasets/api";
import { toast, toastError } from "../lib/toast";
import { Button } from "./ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";

interface DeleteDatasetDialogProps {
  /** The dataset to delete, or null when the dialog is closed. */
  dataset: string | null;
  onOpenChange: (open: boolean) => void;
}

/**
 * Confirm-then-delete a golden set. A 409 (`DatasetInUseError`) is *state, not failure* (ADR 0023):
 * the set is still gating a prompt, so we keep the dialog open and show which prompts must be
 * detached first, rather than firing a generic error toast and closing.
 */
export function DeleteDatasetDialog({ dataset, onOpenChange }: DeleteDatasetDialogProps) {
  const deleteDataset = useDeleteDataset();
  const [inUseMessage, setInUseMessage] = useState<string | null>(null);

  function handleConfirm() {
    if (!dataset) return;
    setInUseMessage(null);
    deleteDataset.mutate(dataset, {
      onSuccess: () => {
        toast.success(`Deleted “${dataset}”`);
        onOpenChange(false);
      },
      onError: (err) => {
        // 409 = still in use; the body's detail names the prompts. Keep the dialog open.
        if (err instanceof ApiError && err.status === 409) {
          setInUseMessage(err.message);
          return;
        }
        toastError(err, "Could not delete the golden set.");
      },
    });
  }

  function handleOpenChange(open: boolean) {
    if (!open) setInUseMessage(null);
    onOpenChange(open);
  }

  return (
    <Dialog open={dataset !== null} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete golden set</DialogTitle>
          <DialogDescription>
            Delete “{dataset}”? This removes the set and all its cases. Past eval results are kept.
          </DialogDescription>
        </DialogHeader>

        {inUseMessage && <p className="text-sm text-destructive">{inUseMessage}</p>}

        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleConfirm}
            disabled={deleteDataset.isPending}
          >
            {deleteDataset.isPending ? "Deleting…" : "Delete"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
