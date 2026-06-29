// Minimal CSV export — turn a row set into a downloadable file. Kept framework-free and pure (the
// download side-effect is a separate, thin helper) so the serialisation is unit-testable.

/** RFC-4180 field quoting: wrap in quotes and double internal quotes when a field needs it. */
function escapeField(value: string): string {
  return /[",\n\r]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

export interface CsvColumn<T> {
  header: string;
  // How to render one row's value for this column. Nullish → empty cell.
  value: (row: T) => string | number | null | undefined;
}

/** Serialise rows to a CSV string (header row + one row each), respecting the column order. */
export function toCsv<T>(rows: T[], columns: CsvColumn<T>[]): string {
  const lines = [columns.map((c) => escapeField(c.header)).join(",")];
  for (const row of rows) {
    lines.push(
      columns
        .map((c) => {
          const v = c.value(row);
          return escapeField(v == null ? "" : String(v));
        })
        .join(","),
    );
  }
  return lines.join("\r\n");
}

/** Trigger a client-side download of `content` as `filename`. No-op outside the browser. */
export function downloadCsv(filename: string, content: string): void {
  if (typeof document === "undefined") return;
  const blob = new Blob([content], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
