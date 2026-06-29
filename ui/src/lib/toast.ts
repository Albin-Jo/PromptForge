import { toast } from "sonner";

// One import for every toast call site, so the whole app reports success/error the
// same way and we can swap the toast library in one place if we ever need to.
export { toast };

// API and fetch errors reach us in a few shapes (Error, our {message} envelope, or a
// bare string). Normalise to a single line and fire an error toast. Returns the message
// so callers can also surface it inline if they want.
export function toastError(error: unknown, fallback = "Something went wrong"): string {
  const message =
    error instanceof Error
      ? error.message
      : typeof error === "string"
        ? error
        : typeof error === "object" && error !== null && "message" in error
          ? String((error as { message: unknown }).message)
          : fallback;
  toast.error(message || fallback);
  return message || fallback;
}
