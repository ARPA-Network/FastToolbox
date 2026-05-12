/**
 * Vercel Cron: POST upstream Python `POST /api/vol-snapshot/refresh` so the disk snapshot updates.
 *
 * Security (required):
 *   Authorization: Bearer <CRON_SECRET>
 * Vercel injects CRON_SECRET when Cron Jobs are enabled; you can also set VOL_SNAPSHOT_CRON_SECRET
 * and call this URL manually with the same Bearer value.
 *
 * Env (Vercel project):
 *   VOL_SNAPSHOT_UPSTREAM_URL — same as proxy, e.g. https://host/api/vol-snapshot
 *   VOL_SNAPSHOT_WRITE_TOKEN — must match Python VOL_MONITOR_WRITE_SECRET (write access)
 *   Optional: VOL_SNAPSHOT_CRON_MODE — "full" | "light" (default full)
 *
 * Note: `full` refresh can run many minutes; `vercel.json` sets maxDuration for this function.
 */
export default async function handler(req, res) {
  if (req.method !== "GET" && req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  const auth = (req.headers.authorization || "").trim();
  const secret =
    process.env.CRON_SECRET || process.env.VOL_SNAPSHOT_CRON_SECRET || "";
  if (!secret || auth !== `Bearer ${secret}`) {
    return res.status(401).json({ error: "Unauthorized" });
  }

  const upstreamBase = (process.env.VOL_SNAPSHOT_UPSTREAM_URL || "").replace(
    /\/$/,
    ""
  );
  const writeToken = (
    process.env.VOL_SNAPSHOT_WRITE_TOKEN ||
    process.env.VOL_MONITOR_WRITE_SECRET ||
    ""
  ).trim();

  if (!upstreamBase || !writeToken) {
    return res.status(503).json({
      error:
        "Missing VOL_SNAPSHOT_UPSTREAM_URL or VOL_SNAPSHOT_WRITE_TOKEN (write secret)",
    });
  }

  const refreshUrl = upstreamBase.endsWith("/refresh")
    ? upstreamBase
    : `${upstreamBase}/refresh`;

  const mode = (process.env.VOL_SNAPSHOT_CRON_MODE || "full").toLowerCase();
  const body = JSON.stringify({ mode: mode === "light" ? "light" : "full" });

  try {
    const r = await fetch(refreshUrl, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${writeToken}`,
        "Content-Type": "application/json",
      },
      body,
      signal: AbortSignal.timeout(290000),
    });
    const text = await r.text();
    res.status(r.status);
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    res.send(text);
  } catch (e) {
    res.status(502).json({
      error: e instanceof Error ? e.message : "upstream refresh failed",
    });
  }
}
