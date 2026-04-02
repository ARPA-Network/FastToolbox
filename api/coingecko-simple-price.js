/**
 * Proxies CoinGecko simple price API (browser cannot call CoinGecko directly — no CORS).
 */
export default async function handler(req, res) {
  if (req.method !== "GET") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  const ids = req.query.ids;
  const vs_currencies = req.query.vs_currencies || "usd";

  if (!ids || typeof ids !== "string") {
    return res.status(400).json({ error: "missing ids" });
  }

  const upstream = `https://api.coingecko.com/api/v3/simple/price?ids=${encodeURIComponent(
    ids
  )}&vs_currencies=${encodeURIComponent(vs_currencies)}`;

  const r = await fetch(upstream);
  const data = await r.json();
  return res.status(r.status).json(data);
}
