// Minimal markdown rendering — we deliberately avoid pulling in a
// markdown library for V1. Heading lines (`# `, `## `, `### `) bump up;
// bullet lines stay flat; everything else flows as a paragraph. Shared
// between CoreRulesTab and the rule-editor section preview dialog.

interface Props {
  text: string;
}

export function MarkdownDoc({ text }: Props) {
  const lines = text.split(/\r?\n/);
  const blocks: Array<{ kind: string; lines: string[] }> = [];
  let current: { kind: string; lines: string[] } | null = null;

  const push = (kind: string, line: string) => {
    if (!current || current.kind !== kind) {
      current = { kind, lines: [line] };
      blocks.push(current);
    } else {
      current.lines.push(line);
    }
  };

  for (const raw of lines) {
    const line = raw;
    if (/^#{1,3}\s+/.test(line)) {
      blocks.push({ kind: "heading", lines: [line] });
      current = null;
    } else if (/^\s*[-*]\s+/.test(line)) {
      push("list", line);
    } else if (line.trim() === "") {
      blocks.push({ kind: "spacer", lines: [] });
      current = null;
    } else {
      push("para", line);
    }
  }

  return (
    <div className="space-y-3 text-[13px] leading-relaxed text-text">
      {blocks.map((block, i) => {
        if (block.kind === "spacer") return <div key={i} className="h-2" />;
        if (block.kind === "heading") {
          const raw = block.lines[0];
          const match = raw.match(/^(#{1,3})\s+(.*)$/);
          if (!match) return <p key={i}>{raw}</p>;
          const level = match[1].length;
          const content = match[2];
          if (level === 1)
            return (
              <h1
                key={i}
                className="text-[20px] font-semibold tracking-tight mt-5 mb-1"
              >
                {content}
              </h1>
            );
          if (level === 2)
            return (
              <h2
                key={i}
                className="text-[16px] font-semibold tracking-tight mt-4 mb-1"
              >
                {content}
              </h2>
            );
          return (
            <h3
              key={i}
              className="text-[14px] font-semibold tracking-tight mt-3 mb-0.5 text-text-2"
            >
              {content}
            </h3>
          );
        }
        if (block.kind === "list") {
          return (
            <ul key={i} className="list-disc ml-6 space-y-0.5">
              {block.lines.map((line, j) => (
                <li key={j}>{line.replace(/^\s*[-*]\s+/, "")}</li>
              ))}
            </ul>
          );
        }
        return (
          <p key={i} className="whitespace-pre-wrap">
            {block.lines.join("\n")}
          </p>
        );
      })}
    </div>
  );
}
