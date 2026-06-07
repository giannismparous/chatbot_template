import { CitationRenderer } from "./CitationRenderer.jsx";
import { SourceList } from "./SourceList.jsx";
import { ConfidenceBadge } from "./ConfidenceBadge.jsx";
import { EscalationCallout } from "./EscalationCallout.jsx";
import { AnswerText } from "./AnswerText.jsx";

function CiteSegment({ text, sources }) {
  return <CitationRenderer text={text} sources={sources} />;
}

export function MessageBubble({ message, showConfidence = true, showSources = true }) {
  if (message.role === "user") {
    return <div className="bubble user">{message.content}</div>;
  }

  const meta = message.meta || {};
  const sources = meta.sources || [];
  const renderCite = (value, key) => <CiteSegment key={key} text={value} sources={sources} />;

  return (
    <div className="assistant-block">
      <div className="bubble assistant">
        {message.streaming ? (
          <span>{message.content}</span>
        ) : (
          <AnswerText text={message.content} renderText={renderCite} />
        )}
      </div>
      {!message.streaming && showSources ? <SourceList sources={meta.sources} /> : null}
      {!message.streaming ? (
        <ConfidenceBadge confidence={meta.confidence} visible={showConfidence} />
      ) : null}
      {!message.streaming ? (
        <EscalationCallout requiresHuman={meta.requires_human} escalation={meta.escalation} />
      ) : null}
    </div>
  );
}
