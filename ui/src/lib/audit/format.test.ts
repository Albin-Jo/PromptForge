import { describe, expect, it } from "vitest";
import { formatAction } from "./format";

describe("formatAction", () => {
  it("maps known actions to friendly labels", () => {
    expect(formatAction("version_created")).toBe("Version created");
    expect(formatAction("label_set")).toBe("Label set");
    expect(formatAction("golden_set_attached")).toBe("Golden set attached");
    expect(formatAction("user_created")).toBe("User created");
    expect(formatAction("promoted")).toBe("Promoted");
  });

  it("degrades to the raw verb for an unknown action", () => {
    // A future action the backend grows must still render — never be hidden.
    expect(formatAction("something_new")).toBe("something_new");
  });
});
