import type { ReactNode } from "react";

function inline(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    return <span key={index}>{part}</span>;
  });
}

export function Markdown({ source }: { source: string }) {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }
    if (line.startsWith("|")) {
      const rows: string[][] = [];
      while (index < lines.length && lines[index].startsWith("|")) {
        const cells = lines[index]
          .split("|")
          .slice(1, -1)
          .map((cell) => cell.trim());
        if (!cells.every((cell) => /^:?-+:?$/.test(cell))) rows.push(cells);
        index += 1;
      }
      blocks.push(
        <div key={`t-${index}`} className="my-3 overflow-x-auto">
          <table className="w-full min-w-[32rem] border-collapse text-sm">
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={rowIndex} className={rowIndex === 0 ? "font-medium" : "border-t border-line"}>
                  {row.map((cell, cellIndex) => (
                    <td key={cellIndex} className="px-2 py-1.5 text-left align-top">
                      {inline(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (line.startsWith("# ")) {
      blocks.push(
        <h2 key={index} className="mt-4 font-serif text-2xl text-ink">
          {inline(line.slice(2))}
        </h2>,
      );
      index += 1;
      continue;
    }
    if (line.startsWith("## ")) {
      blocks.push(
        <h3 key={index} className="mt-4 font-serif text-xl text-ink">
          {inline(line.slice(3))}
        </h3>,
      );
      index += 1;
      continue;
    }
    if (line.startsWith("- ")) {
      const items: string[] = [];
      while (index < lines.length && lines[index].startsWith("- ")) {
        items.push(lines[index].slice(2));
        index += 1;
      }
      blocks.push(
        <ul key={`l-${index}`} className="my-2 list-disc space-y-1 pl-5 text-sm leading-6">
          {items.map((item, itemIndex) => (
            <li key={itemIndex}>{inline(item)}</li>
          ))}
        </ul>,
      );
      continue;
    }
    const paragraph: string[] = [];
    while (index < lines.length && lines[index].trim() && !lines[index].startsWith("#") && !lines[index].startsWith("|") && !lines[index].startsWith("- ")) {
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push(
      <p key={`p-${index}`} className="my-2 text-sm leading-6 text-ink">
        {inline(paragraph.join(" "))}
      </p>,
    );
  }

  return <article>{blocks}</article>;
}
