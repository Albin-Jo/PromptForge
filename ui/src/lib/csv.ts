// CSV utilities: export (serialise rows → downloadable file) and import (parse CSV → dataset cases).
// Both sides are kept framework-free and pure so they are unit-testable without a DOM.

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

// --- CSV import (parse) ---------------------------------------------------

export interface CsvParseResult {
  rows: Array<{ input: string; reference: string | null }>;
  errors: Array<{ rowIndex: number; message: string }>;
}

/**
 * Tokenise a CSV string into a 2-D array of cells.
 * Handles RFC-4180 quoting (fields wrapped in `""`), doubled-quote escapes (`""`  → `"`),
 * embedded commas, and both CRLF and LF line endings.
 */
function tokenize(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let inQuotes = false;
  let i = 0;

  while (i < text.length) {
    const ch = text[i];

    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          cell += '"';
          i += 2;
        } else {
          inQuotes = false;
          i++;
        }
      } else {
        cell += ch;
        i++;
      }
    } else if (ch === '"') {
      inQuotes = true;
      i++;
    } else if (ch === ',') {
      row.push(cell);
      cell = "";
      i++;
    } else if (ch === '\r' || ch === '\n') {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
      if (ch === '\r' && text[i + 1] === '\n') i++;
      i++;
    } else {
      cell += ch;
      i++;
    }
  }

  // Flush trailing cell and row.
  if (cell !== "" || row.length > 0) {
    row.push(cell);
    rows.push(row);
  }

  return rows;
}

/**
 * Parse a CSV string into dataset cases.
 * Requires a column named `"input"` (case-insensitive). The `referenceHeader` parameter
 * names the optional reference column (defaults to `"reference"`).
 * Returns parsed rows and per-row validation errors.
 */
export function fromCsv(text: string, referenceHeader = "reference"): CsvParseResult {
  const cells = tokenize(text.trim());
  if (cells.length === 0) return { rows: [], errors: [] };

  const headers = cells[0].map((h) => h.trim().toLowerCase());
  const inputIdx = headers.indexOf("input");
  const refIdx = headers.indexOf(referenceHeader.toLowerCase());

  const errors: CsvParseResult["errors"] = [];
  if (inputIdx === -1) {
    errors.push({ rowIndex: 0, message: `Required column "input" not found in header row.` });
    return { rows: [], errors };
  }

  const rows: CsvParseResult["rows"] = [];
  for (let r = 1; r < cells.length; r++) {
    const cols = cells[r];
    const inputVal = (cols[inputIdx] ?? "").trim();
    if (inputVal === "") {
      errors.push({ rowIndex: r, message: `Row ${r}: "input" is empty — row skipped.` });
      continue;
    }
    const refVal = refIdx !== -1 ? (cols[refIdx] ?? "").trim() : null;
    rows.push({ input: inputVal, reference: refVal === "" || refVal === null ? null : refVal });
  }

  return { rows, errors };
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
