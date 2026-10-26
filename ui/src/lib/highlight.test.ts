import { codeTokens } from "./highlight";

describe("codeTokens", () => {
  it("colors SQL keywords without emitting style markup", () => {
    const tokens = codeTokens("SELECT region AS name FROM sales GROUP BY region");
    const keywords = tokens.filter((token) => token.kind === "keyword").map((token) => token.text);
    expect(keywords).toEqual(["SELECT", "AS", "FROM", "GROUP", "BY"]);
    const rendered = tokens.map((token) => token.text).join("");
    expect(rendered).toBe("SELECT region AS name FROM sales GROUP BY region");
    expect(rendered).not.toContain("color:#e4c27a");
  });

  it("keeps quoted text intact, including words that look like keywords", () => {
    const tokens = codeTokens("SELECT 'FROM sales' AS label");
    expect(tokens.find((token) => token.kind === "string")?.text).toBe("'FROM sales'");
    expect(tokens.filter((token) => token.kind === "keyword").map((token) => token.text)).toEqual(["SELECT", "AS"]);
  });
});
