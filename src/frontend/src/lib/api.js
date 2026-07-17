import { useEffect, useState } from "react";

async function get(path) {
  const response = await fetch(path);
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (body.detail) detail = body.detail;
    } catch {
      /* response had no JSON body; the status line is all we have */
    }
    throw new Error(detail);
  }
  return response.json();
}

/** Fetch on mount and whenever `path` changes. */
export function useApi(path) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    get(path)
      .then((body) => {
        if (!cancelled) setData(body);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [path]);

  return { data, error, loading };
}

export const fmtTHB = (value) => {
  if (value === null || value === undefined) return "—";
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(0)}K`;
  return value.toFixed(0);
};

export const fmtFull = (value) =>
  value === null || value === undefined
    ? "—"
    : value.toLocaleString("en-US", { maximumFractionDigits: 0 });

export const fmtDate = (value) =>
  value ? new Date(value).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "—";

export const titleCase = (value) =>
  (value || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
