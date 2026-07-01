import { useState } from "react";
import { ApiError } from "../lib/api";
import { useDeleteBlock } from "../lib/blocks/api";
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

interface DeleteBlockDialogProps {
  /** The block to delete, or null when the dialog is closed. */
  block: string | null;
  onOpenChange: (open: boolean) => void;
  /** Called after a successful delete — the detail page uses it to navigate away. */
  onDeleted: () => void;
}

/**
 * Confirm-then-delete a block. A 409 (`BlockInUseError`) is *state, not failure* (ADR 0023/0027):
 * a prompt or another block still composes with it, so we keep the dialog open and show which
 * versions must be detached first, rather than firing a generic error toast and closing.
 */
export function DeleteBlockDialog({ block, onOpenChange, onDeleted }: DeleteBlockDialogProps) {
  const deleteBlock = useDeleteBlock();
  const [inUseMessage, setInUseMessage] = useState<string | null>(null);

  function handleConfirm() {
    if (!block) return;
    setInUseMessage(null);
    deleteBlock.mutate(block, {
      onSuccess: () => {
        toast.success(`Deleted “${block}”`);
        onDeleted();
      },
      onError: (err) => {
        // 409 = still composed with; the body's detail names the prompt/block versions. Stay open.
        if (err instanceof ApiError && err.status === 409) {
          setInUseMessage(err.message);
          return;
        }
        toastError(err, "Could not delete the block.");
      },
    });
  }

  function handleOpenChange(open: boolean) {
    if (!open) setInUseMessage(null);
    onOpenChange(open);
  }

  return (
    <Dialog open={block !== null} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete block</DialogTitle>
          <DialogDescription>
            Delete “{block}”? This removes the block and all its versions. It’s refused while any
            prompt or block still composes with it.
          </DialogDescription>
        </DialogHeader>

        {inUseMessage && <p className="text-sm text-destructive">{inUseMessage}</p>}

        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={handleConfirm} disabled={deleteBlock.isPending}>
            {deleteBlock.isPending ? "Deleting…" : "Delete"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
