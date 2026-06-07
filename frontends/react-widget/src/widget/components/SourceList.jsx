import { isPublicSource } from "../citations.js";

function dedupeSources(sources) {
  const seen = new Set();
  return (sources || []).filter(isPublicSource).filter((s) => {
    const key = String(s.url || "").trim().replace(/\/$/, "");
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function sourceLabel(source) {
  const title = String(source.title || "").trim();
  if (title && !title.toLowerCase().endsWith(".md")) return title;
  try {
    const parsed = new URL(source.url);
    return parsed.hostname + (parsed.pathname === "/" ? "" : parsed.pathname);
  } catch {
    return title || "Source";
  }
}

export function SourceList({ sources }) {
  const publicSources = dedupeSources(sources);
  if (!publicSources.length) return null;

  return (
    <div className="source-list" role="navigation" aria-label="Sources">
      <div className="source-list-title">Sources</div>
      <ul className="source-cards">
        {publicSources.map((s) => (
          <li key={`${s.index}-${s.url}`}>
            <a className="source-card" href={s.url} target="_blank" rel="noopener noreferrer">
              <span className="source-card-index">[{s.index}]</span>
              <span className="source-card-body">
                <span className="source-card-title">{sourceLabel(s)}</span>
                <span className="source-card-url">{s.url}</span>
              </span>
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
