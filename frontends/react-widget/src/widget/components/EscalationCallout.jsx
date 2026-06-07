export function EscalationCallout({ requiresHuman, escalation }) {
  if (!requiresHuman && !escalation) return null;
  const message = escalation?.message || "A team member may need to assist with this request.";
  const hint = escalation?.contact_hint;
  return (
    <div className="escalation-callout" role="status">
      <strong>Handoff suggested</strong>
      <p>{message}</p>
      {hint ? <p className="escalation-hint">{hint}</p> : null}
    </div>
  );
}
