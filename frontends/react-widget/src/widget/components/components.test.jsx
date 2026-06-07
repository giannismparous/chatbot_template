import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { splitAnswerBlocks } from "./AnswerText.jsx";
import { CitationRenderer } from "./CitationRenderer.jsx";
import { ConfidenceBadge } from "./ConfidenceBadge.jsx";
import { EscalationCallout } from "./EscalationCallout.jsx";
import { MessageBubble } from "./MessageBubble.jsx";

describe("splitAnswerBlocks", () => {
  it("splits paragraphs and bullets", () => {
    const blocks = splitAnswerBlocks("Line one.\n\n* Bullet item\n\nLine two.");
    expect(blocks).toHaveLength(3);
    expect(blocks[1].type).toBe("bullet");
  });
});

describe("CitationRenderer", () => {
  it("links [1] only when matching public source exists", () => {
    const html = renderToStaticMarkup(
      <CitationRenderer
        text="See [1] and [99]."
        sources={[{ index: 1, title: "Doc", url: "https://example.com/doc" }]}
      />,
    );
    expect(html).toContain('href="https://example.com/doc"');
    expect(html).toContain("<span>[99]</span>");
    expect(html).not.toContain('>[99]</a>');
  });

  it("renders orphan markers as plain text", () => {
    const html = renderToStaticMarkup(<CitationRenderer text="Ref [99]" sources={[]} />);
    expect(html).toContain("[99]");
    expect(html).not.toContain("cite-chip");
  });
});

describe("ConfidenceBadge", () => {
  it("renders human-friendly level", () => {
    const html = renderToStaticMarkup(
      <ConfidenceBadge confidence={{ level: "medium", reason: "Moderate match." }} />,
    );
    expect(html).toContain("Confidence: medium");
  });

  it("hides none level", () => {
    const html = renderToStaticMarkup(
      <ConfidenceBadge confidence={{ level: "none", reason: "No knowledge." }} />,
    );
    expect(html).toBe("");
  });
});

describe("EscalationCallout", () => {
  it("renders handoff callout", () => {
    const html = renderToStaticMarkup(
      <EscalationCallout
        requiresHuman
        escalation={{ message: "Please contact support.", contact_hint: "support@example.com" }}
      />,
    );
    expect(html).toContain("Handoff suggested");
    expect(html).toContain("Please contact support.");
    expect(html).toContain("support@example.com");
  });
});

describe("MessageBubble", () => {
  it("never renders trace object", () => {
    const html = renderToStaticMarkup(
      <MessageBubble
        message={{
          role: "assistant",
          content: "Answer",
          meta: {
            sources: [],
            confidence: { level: "high", reason: "ok" },
            trace: { retrieval: ["secret"] },
          },
        }}
      />,
    );
    expect(html).not.toContain("retrieval");
    expect(html).not.toContain("trace");
    expect(html).not.toContain("secret");
  });
});
