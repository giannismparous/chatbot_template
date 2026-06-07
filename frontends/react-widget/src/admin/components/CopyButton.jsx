export function CopyButton({ text, label = "Copy" }) {
  async function onCopy() {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      /* ignore */
    }
  }
  return (
    <button type="button" className="admin-btn secondary" onClick={onCopy}>
      {label}
    </button>
  );
}
