export type Crumb = { label: string; to?: string };

// Pure pathname -> breadcrumb trail. Kept free of React so it's trivially unit-testable.
// The last crumb is the current page (no link). Prompt names arrive URL-encoded — decode
// for display but keep the encoded form in hrefs.
export function buildBreadcrumbs(pathname: string): Crumb[] {
  const segments = pathname.split("/").filter(Boolean);

  // The index route is the fleet overview; /overview redirects here but may flash a crumb.
  if (segments.length === 0 || segments[0] === "overview") return [{ label: "Overview" }];

  if (segments[0] === "prompts") {
    // The prompt list itself is the current page → a plain label, no self-link.
    if (segments.length === 1) return [{ label: "Prompts" }];

    const trail: Crumb[] = [{ label: "Prompts", to: "/prompts" }];

    if (segments[1] === "new") {
      trail.push({ label: "New prompt" });
      return trail;
    }

    const encodedName = segments[1] ?? "";
    const name = safeDecode(encodedName);

    // ["prompts", name, "edit"|"versions"|"dashboard"]
    if (segments.length === 3) {
      const leaf = { edit: "Editor", versions: "Versions", dashboard: "Dashboard" }[
        segments[2]
      ];
      trail.push({ label: name, to: `/prompts/${encodedName}/edit` });
      trail.push({ label: leaf ?? segments[2] });
      return trail;
    }

    // ["prompts", name, "versions", v, "playground"|"scan"]
    if (segments.length === 5 && segments[2] === "versions") {
      const leaf = { playground: "Playground", scan: "Scan" }[segments[4]];
      trail.push({ label: name, to: `/prompts/${encodedName}/versions` });
      trail.push({ label: `Version ${segments[3]}` });
      trail.push({ label: leaf ?? segments[4] });
      return trail;
    }

    trail.push({ label: name });
    return trail;
  }

  if (segments[0] === "datasets") {
    // The list is the current page → a plain label, no self-link.
    if (segments.length === 1) return [{ label: "Golden sets" }];

    const trail: Crumb[] = [{ label: "Golden sets", to: "/datasets" }];

    if (segments[1] === "new") {
      trail.push({ label: "New golden set" });
      return trail;
    }

    // ["datasets", name, "edit"] — there's no dataset *detail* route (only .../edit), so the name is
    // a plain label, not a link to a page that would render blank.
    const encodedName = segments[1] ?? "";
    trail.push({ label: safeDecode(encodedName) });
    if (segments[2] === "edit") trail.push({ label: "Edit" });
    return trail;
  }

  if (segments[0] === "blocks") {
    if (segments.length === 1) return [{ label: "Blocks" }];

    const trail: Crumb[] = [{ label: "Blocks", to: "/blocks" }];

    if (segments[1] === "new") {
      trail.push({ label: "New block" });
      return trail;
    }

    const encodedName = segments[1] ?? "";
    const name = safeDecode(encodedName);

    // ["blocks", name, "versions", "new"] — name is a linked parent of the new-version page.
    if (segments.length === 4 && segments[2] === "versions" && segments[3] === "new") {
      trail.push({ label: name, to: `/blocks/${encodedName}` });
      trail.push({ label: "New version" });
      return trail;
    }

    // ["blocks", name] — the detail page is the current page, so the name is a plain label.
    trail.push({ label: name });
    return trail;
  }

  if (segments[0] === "users") return [{ label: "Users" }];

  return [{ label: "Overview" }];
}

function safeDecode(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}
