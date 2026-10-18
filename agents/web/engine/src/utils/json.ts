export function jsonText(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

export function mcpText(value: unknown) {
  return {
    content: [{ type: "text" as const, text: typeof value === "string" ? value : jsonText(value) }],
  };
}

export function mcpError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error);
  return {
    isError: true,
    content: [{ type: "text" as const, text: message }],
  };
}
