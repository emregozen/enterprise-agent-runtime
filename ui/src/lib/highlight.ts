export type CodeToken = { kind: "text" | "keyword" | "string"; text: string };

const TOKEN = /(['"])(?:\\.|(?!\1).)*\1|\b(?:SELECT|FROM|WHERE|GROUP|BY|ORDER|LIMIT|AND|OR|AS|JOIN|ON|CAST)\b/g;

/** One pass so keyword markup is never matched again as a quoted string. */
export function codeTokens(code: string): CodeToken[] {
  const tokens: CodeToken[] = [];
  let last = 0;
  for (const match of code.matchAll(TOKEN)) {
    const start = match.index ?? 0;
    if (start > last) tokens.push({ kind: "text", text: code.slice(last, start) });
    const text = match[0];
    const quoted = text.startsWith("'") || text.startsWith('"');
    tokens.push({ kind: quoted ? "string" : "keyword", text });
    last = start + text.length;
  }
  if (last < code.length) tokens.push({ kind: "text", text: code.slice(last) });
  return tokens;
}
