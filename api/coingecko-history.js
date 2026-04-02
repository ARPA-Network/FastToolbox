/**
 * Proxies CoinGecko coin history by date (browser cannot call CoinGecko directly — no CORS).
 */
export default async function handler(req, res) {
  if (req.method !== "GET") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  const id = req.query.id;
  const date = req.query.date;

  if (!id || typeof id !== "string" || !date || typeof date !== "string") {
    return res.status(400).json({ error: "missing id or date" });
  }

  const upstream = `https://api.coingecko.com/api/v3/coins/${encodeURIComponent(
    id
  )}/history?date=${encodeURIComponent(date)}`;

  const r = await fetch(upstream);
  const data = await r.json();
  return res.status(r.status).json(data);
}
