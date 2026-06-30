import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// jsdom lacks a few browser APIs that cmdk / Radix overlays touch at mount. Stub them so
// the command palette and dialog-based primitives can render in tests.
if (!("ResizeObserver" in globalThis)) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = vi.fn();
}
// Radix Select/overlays call the Pointer Capture API on open; jsdom doesn't implement it, so
// stub the three methods (guarded) to let those overlays actually open under userEvent.
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
}

// React Testing Library doesn't auto-clean between tests under Vitest's globals.
afterEach(() => {
  cleanup();
});
