const BOLD_RE = /\*\*(.+?)\*\*/g;

function renderInline(text, renderText) {
  const parts = [];
  let last = 0;
  for (const match of String(text || "").matchAll(BOLD_RE)) {
    const idx = match.index ?? 0;
    if (idx > last) parts.push(renderText(text.slice(last, idx), `t-${last}`));
    parts.push(<strong key={`b-${idx}`}>{match[1]}</strong>);
    last = idx + match[0].length;
  }
  if (last < text.length) parts.push(renderText(text.slice(last), `t-${last}`));
  return parts.length ? parts : [renderText(text, "t-full")];
}

export function splitAnswerBlocks(text) {
  const lines = String(text || "").split("\n");
  const blocks = [];
  let paragraph = [];

  function flushParagraph() {
    if (paragraph.length) {
      blocks.push({ type: "paragraph", lines: paragraph });
      paragraph = [];
    }
  }

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) {
      flushParagraph();
      continue;
    }
    const bulletMatch = line.match(/^[*-]\s+(.*)$/);
    if (bulletMatch) {
      flushParagraph();
      blocks.push({ type: "bullet", text: bulletMatch[1] });
      continue;
    }
    paragraph.push(line);
  }
  flushParagraph();
  return blocks.length ? blocks : [{ type: "paragraph", lines: [""] }];
}

export function AnswerText({ text, renderText }) {
  const cite = renderText || ((value, key) => <span key={key}>{value}</span>);
  const blocks = splitAnswerBlocks(text);

  return (
    <div className="answer-text">
      {blocks.map((block, idx) => {
        if (block.type === "bullet") {
          return (
            <p key={idx} className="answer-bullet">
              • {renderInline(block.text, cite)}
            </p>
          );
        }
        const joined = block.lines.join(" ");
        return <p key={idx}>{renderInline(joined, cite)}</p>;
      })}
    </div>
  );
}
