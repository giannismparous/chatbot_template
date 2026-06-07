import { splitCitationSegments, isPublicSource } from "../citations.js";

export function CitationRenderer({ text, sources }) {
  const byIndex = new Map(sources.map((s) => [s.index, s]));
  const segments = splitCitationSegments(text);

  return (
    <span className="citation-text">
      {segments.map((seg, idx) => {
        if (seg.type === "text") return <span key={idx}>{seg.value}</span>;
        const source = byIndex.get(seg.value);
        if (!source || !isPublicSource(source)) {
          return <span key={idx}>[{seg.value}]</span>;
        }
        return (
          <a
            key={idx}
            className="cite-chip"
            href={source.url}
            target="_blank"
            rel="noopener noreferrer"
            title={source.title}
          >
            [{seg.value}]
          </a>
        );
      })}
    </span>
  );
}
