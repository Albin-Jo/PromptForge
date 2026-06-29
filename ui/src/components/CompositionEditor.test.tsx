import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CompositionEditor } from "./CompositionEditor";
import type { BlockRef } from "../lib/prompts/types";

// Two blocks in the catalog; "guardrails" has two versions so we can test re-pinning.
vi.mock("../lib/blocks/api", () => ({
  useBlocks: () => ({
    data: [
      {
        id: "blk-1",
        name: "guardrails",
        role: "guardrails",
        description: null,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
        versions: [
          { id: "g1", version_number: 1, parent_version_id: null, content: "", input_variables: [], created_at: "2026-01-01T00:00:00Z" },
          { id: "g2", version_number: 2, parent_version_id: "g1", content: "", input_variables: [], created_at: "2026-01-02T00:00:00Z" },
        ],
      },
      {
        id: "blk-2",
        name: "tone",
        role: "context",
        description: null,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
        versions: [
          { id: "t1", version_number: 1, parent_version_id: null, content: "", input_variables: [], created_at: "2026-01-01T00:00:00Z" },
        ],
      },
    ],
    isPending: false,
    isError: false,
    error: null,
  }),
  useBlockImpact: () => ({ data: undefined, isFetching: false, isError: false }),
}));

describe("CompositionEditor", () => {
  it("adds a block pinned to its latest version", async () => {
    const onChange = vi.fn<(next: BlockRef[]) => void>();
    const user = userEvent.setup();
    render(<CompositionEditor value={[]} onChange={onChange} />);

    await user.selectOptions(screen.getByLabelText(/add a block/i), "guardrails");
    await user.click(screen.getByRole("button", { name: /add block/i }));

    // guardrails' latest version is 2 -> that's what gets pinned.
    expect(onChange).toHaveBeenCalledWith([{ block: "guardrails", version: 2 }]);
  });

  it("removes a block", async () => {
    const onChange = vi.fn<(next: BlockRef[]) => void>();
    const user = userEvent.setup();
    render(
      <CompositionEditor value={[{ block: "guardrails", version: 2 }]} onChange={onChange} />,
    );
    await user.click(screen.getByRole("button", { name: /remove guardrails/i }));
    expect(onChange).toHaveBeenCalledWith([]);
  });

  it("reorders blocks with the up control", async () => {
    const onChange = vi.fn<(next: BlockRef[]) => void>();
    const user = userEvent.setup();
    render(
      <CompositionEditor
        value={[
          { block: "guardrails", version: 2 },
          { block: "tone", version: 1 },
        ]}
        onChange={onChange}
      />,
    );
    await user.click(screen.getByRole("button", { name: /move tone up/i }));
    expect(onChange).toHaveBeenCalledWith([
      { block: "tone", version: 1 },
      { block: "guardrails", version: 2 },
    ]);
  });

  it("re-pins a block to an older version", async () => {
    const onChange = vi.fn<(next: BlockRef[]) => void>();
    const user = userEvent.setup();
    render(
      <CompositionEditor value={[{ block: "guardrails", version: 2 }]} onChange={onChange} />,
    );
    await user.selectOptions(screen.getByLabelText(/pinned version for guardrails/i), "1");
    expect(onChange).toHaveBeenCalledWith([{ block: "guardrails", version: 1 }]);
  });

  it("does not offer an already-composed block in the add picker", () => {
    render(
      <CompositionEditor value={[{ block: "guardrails", version: 2 }]} onChange={vi.fn()} />,
    );
    const picker = screen.getByLabelText(/add a block/i);
    expect(picker).toHaveTextContent("tone");
    expect(picker).not.toHaveTextContent("guardrails");
  });
});
