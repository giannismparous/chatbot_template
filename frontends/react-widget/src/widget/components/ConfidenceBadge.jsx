export function ConfidenceBadge({ confidence, visible = true }) {
  if (!visible || !confidence) return null;
  const level = confidence.level || "medium";
  if (level === "none") return null;
  return (
    <div className={`confidence-badge level-${level}`} title={confidence.reason || ""}>
      Confidence: {level}
    </div>
  );
}
