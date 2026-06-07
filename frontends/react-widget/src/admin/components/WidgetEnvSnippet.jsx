import { buildWidgetEnvSnippet } from "../utils/widgetEnvSnippet.js";
import { CopyButton } from "./CopyButton.jsx";

export function WidgetEnvSnippet({ clientId, widgetKey, keyPrefix }) {
  const snippet = buildWidgetEnvSnippet({ clientId, widgetKey, keyPrefix });
  return (
    <div className="admin-section">
      <h4>Widget .env snippet</h4>
      {!widgetKey && keyPrefix ? (
        <p className="admin-note">
          Full widget key is not in memory (prefix: {keyPrefix}). Create a new client if you lost the key.
        </p>
      ) : null}
      <pre className="admin-code">{snippet}</pre>
      <CopyButton text={snippet} label="Copy .env snippet" />
    </div>
  );
}
