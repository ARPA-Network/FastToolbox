/**
 * Same-origin proxy: the browser calls `/api/vol-snapshot-proxy` only; real secrets stay in Vercel env.
 *
 * Environment:
 *   VOL_SNAPSHOT_UPSTREAM_URL — full Python API URL, e.g. https://api.example.com/api/vol-snapshot
 *   VOL_SNAPSHOT_PROXY_TOKEN — must match VOL_MONITOR_READ_SECRET on the Python service
 *
 * Scheduled disk refresh (server): see `/api/vol-snapshot-cron-refresh` + `vercel.json` crons.
 */
export default async function handler(req, res) {
  if (req.method !== "GET") {
    res.status(405).json({ error: "Method not allowed" });
    return;
  }

  const upstream = process.env.VOL_SNAPSHOT_UPSTREAM_URL;
  const token =
    process.env.VOL_SNAPSHOT_PROXY_TOKEN ||
    process.env.VOL_MONITOR_READ_SECRET;

  if (!upstream || !token) {
    res
      .status(503)
      .json({
        error:
          "Snapshot proxy not configured (VOL_SNAPSHOT_UPSTREAM_URL + VOL_SNAPSHOT_PROXY_TOKEN)",
      });
    return;
  }

  try {
    const r = await fetch(upstream, {
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(120000),
    });
    const text = await r.text();
    res.status(r.status);
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    res.send(text);
  } catch (e) {
    res.status(502).json({
      error: e instanceof Error ? e.message : "upstream fetch failed",
    });
  }
}
