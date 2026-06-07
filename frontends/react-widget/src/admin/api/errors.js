export class AdminApiError extends Error {
  constructor(message, { status = 0, reason = null, detail = null } = {}) {
    super(message);
    this.name = "AdminApiError";
    this.status = status;
    this.reason = reason;
    this.detail = detail;
  }
}

export async function readJsonResponse(res) {
  const text = await res.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    throw new AdminApiError("Invalid JSON response from admin API.", { status: res.status });
  }
}

export function normalizeAdminError(res, body) {
  const status = res.status;
  const detail = body?.detail;

  if (status === 401 || status === 403) {
    return new AdminApiError("Invalid or missing admin token.", { status });
  }

  if (status === 409 && detail && typeof detail === "object") {
    const reason = detail.reason || "conflict";
    const msg = detail.detail || `Deploy blocked (${reason}).`;
    return new AdminApiError(msg, { status, reason, detail: detail.detail });
  }

  if (typeof detail === "string") {
    return new AdminApiError(detail, { status });
  }

  return new AdminApiError(`Admin request failed (${status}).`, { status });
}

export function adminHeaders(token, extra = {}) {
  return {
    ...extra,
    "x-admin-token": token,
  };
}
