export function StatusBadge({ status, label }) {
  const cls = `status-badge status-${status || "unknown"}`;
  return <span className={cls}>{label || status || "unknown"}</span>;
}
