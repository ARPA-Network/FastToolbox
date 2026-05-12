<script lang="ts">
  import { onDestroy, onMount } from "svelte";

  const TARGETS = ["ARPAUSDT", "BELUSDT"] as const;
  const AUTO_REFRESH_MINUTES = 30;
  /** Browser auto-refresh for weekly/monthly fetch. Not read from server `.env`; see `VOL_MONITOR_FULL_MARKET_TTL_SEC` (Python full-market cache TTL) for a different knob. */
  const WEEKLY_REFRESH_MINUTES = 720;
  const EXCHANGE_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo";
  const TICKER_24HR_URL = "https://api.binance.com/api/v3/ticker/24hr";
  const KLINES_INTERVAL_MS = 200;
  const KLINE_LIMIT = 35;
  const KLINE_CACHE_PREFIX = "volMon_klines_v1_";
  const KLINE_CACHE_TTL_MS = 5 * 60 * 1000;
  const LS_SNAPSHOT_URL_KEY = "volMon_rank_snapshot_url";
  /**
   * Default: Vercel same-origin proxy (secret stays server-side). If proxy returns 503, falls back to browser klines.
   * Local Python: override via localStorage `volMon_rank_snapshot_url` or `?rankSnapshot=`.
   */
  const RANK_SNAPSHOT_URL_DEFAULT = "/api/vol-snapshot-proxy";

  /** `AbortSignal.timeout` is missing on some browsers; without this, fetch throws synchronously and snapshot load fails silently (empty ranks). */
  function fetchSignal(ms: number): AbortSignal {
    const AS = typeof AbortSignal !== "undefined" ? AbortSignal : null;
    if (AS && typeof (AS as unknown as { timeout?: (n: number) => AbortSignal }).timeout === "function") {
      return (AS as unknown as { timeout: (n: number) => AbortSignal }).timeout(ms);
    }
    const c = new AbortController();
    setTimeout(() => c.abort(), ms);
    return c.signal;
  }

  type RankInfo = {
    rank: number;
    total: number;
    percentile: number;
  };

  type LongVol = {
    qv7: number | null;
    qv30: number | null;
    longSrc: string;
    longErr: string | null;
    /** Spot-universe 24h rank from rank snapshot (same `universe_total` as server); not from browser ticker. */
    rank24?: number;
    total24?: number;
    pct24?: number;
    rank7?: number;
    total7?: number;
    pct7?: number;
    rank30?: number;
    total30?: number;
    pct30?: number;
  };

  type VolCard = {
    symbol: string;
    volume: string;
    spot: RankInfo | null;
    all: RankInfo | null;
    cardWarn: boolean;
    longVol: LongVol;
  };

  type VolCardRow =
    | { kind: "card"; item: VolCard }
    | { kind: "missing"; symbol: string; message: string };

  type State24h = {
    raw: Array<{ symbol: string; quoteVolume: string }>;
    spotUsdt: Array<{ symbol: string; quoteVolume: string }>;
    allUsdt: Array<{ symbol: string; quoteVolume: string }>;
    updatedAt: number;
  };

  type RankSnapTarget = {
    rank_24h?: number;
    total_24h?: number;
    percentile_24h?: number;
    qv_24h?: number;
    qv_7d?: number;
    qv_30d?: number;
    rank_7d?: number;
    total_7d?: number;
    percentile_7d?: number;
    rank_30d?: number;
    total_30d?: number;
    percentile_30d?: number;
  };

  type RankSnap = {
    full_market_cache_updated_at?: number;
    /** Present when snapshot was built with `mode: "light"` (no full-market 7d/30d ranks). */
    mode?: string;
    targets?: Record<string, RankSnapTarget>;
  };

  let state24h: State24h | null = null;
  let stateWeekly: {
    longVolBySymbol: Record<string, LongVol>;
    updatedAt: number;
    rankSnap: RankSnap | null;
  } | null = null;

  let sampleNote = "";
  let updateLine24h = "";
  let updateLineWeekly = "";
  let countdownLine24h = "";
  let countdownLineWeekly = "";
  let loadingInitial = true;
  let refresh24hBusy = false;
  let refreshWeeklyBusy = false;
  let errorTitle: string | null = null;
  let errorMsg: string | null = null;
  let rows: VolCardRow[] = [];

  let countdownTimer: ReturnType<typeof setInterval> | null = null;
  let timer24h: ReturnType<typeof setTimeout> | null = null;
  let timerWeekly: ReturnType<typeof setTimeout> | null = null;
  let next24hAt = 0;
  let nextWeeklyAt = 0;

  function getRankSnapshotUrl(): string {
    if (typeof window === "undefined") return "";
    try {
      const q = new URLSearchParams(window.location.search).get("rankSnapshot");
      if (q != null && String(q).trim()) return String(q).trim();
    } catch {
      /* ignore */
    }
    try {
      const ls = localStorage.getItem(LS_SNAPSHOT_URL_KEY);
      if (ls != null && String(ls).trim()) return String(ls).trim();
    } catch {
      /* ignore */
    }
    return String(RANK_SNAPSHOT_URL_DEFAULT || "").trim();
  }

  function formatUpdateLine(prefix: string, ts: number | null | undefined) {
    if (ts == null || !Number.isFinite(ts)) return `${prefix}: —`;
    return `${prefix}: ${new Date(ts).toLocaleString("en-US", {
      timeZone: "Asia/Shanghai",
    })}`;
  }

  function buildSpotUsdtSymbolSet(exchangeJson: {
    symbols: Array<{
      symbol: string;
      quoteAsset: string;
      status: string;
      isSpotTradingAllowed: boolean;
    }>;
  }) {
    const set = new Set<string>();
    for (const s of exchangeJson.symbols) {
      if (s.quoteAsset !== "USDT") continue;
      if (s.status !== "TRADING") continue;
      if (!s.isSpotTradingAllowed) continue;
      set.add(s.symbol);
    }
    return set;
  }

  function sortByQuoteVolumeDesc(
    r: Array<{ quoteVolume: string; symbol: string }>
  ) {
    r.sort(
      (a, b) => parseFloat(b.quoteVolume) - parseFloat(a.quoteVolume)
    );
  }

  function rankPercentile(
    sortedRows: Array<{ symbol: string }>,
    symbol: string
  ): RankInfo | null {
    const index = sortedRows.findIndex((x) => x.symbol === symbol);
    if (index === -1) return null;
    const rank = index + 1;
    const total = sortedRows.length;
    const percentile = rank / total;
    return { rank, total, percentile };
  }

  function bottom20Status(percentile: number) {
    const bad = percentile > 0.8;
    return {
      bad,
      text: bad ? "⚠️ Bottom 20%!" : "✅ OK (not in bottom 20%)",
    };
  }

  function fmtPct(p: number) {
    return (p * 100).toFixed(2) + "%";
  }

  function fmtUsdt(n: number | null | undefined) {
    if (n == null || Number.isNaN(n)) return "—";
    return Math.round(n).toLocaleString("en-US");
  }

  function sleep(ms: number) {
    return new Promise<void>((resolve) => setTimeout(resolve, ms));
  }

  function loadKlineCache(symbol: string): { qv7: number; qv30: number } | null {
    if (typeof localStorage === "undefined") return null;
    try {
      const raw = localStorage.getItem(KLINE_CACHE_PREFIX + symbol);
      if (!raw) return null;
      const o = JSON.parse(raw) as { ts?: number; qv7?: number; qv30?: number };
      if (Date.now() - (o.ts ?? 0) > KLINE_CACHE_TTL_MS) return null;
      if (o.qv7 == null || o.qv30 == null) return null;
      return { qv7: o.qv7, qv30: o.qv30 };
    } catch {
      return null;
    }
  }

  function saveKlineCache(symbol: string, qv7: number, qv30: number) {
    if (typeof localStorage === "undefined") return;
    try {
      localStorage.setItem(
        KLINE_CACHE_PREFIX + symbol,
        JSON.stringify({ ts: Date.now(), qv7, qv30 })
      );
    } catch {
      /* quota */
    }
  }

  /** Sum quote volume (klines[i][7]) over the last n daily candles. */
  function sumQuoteVolLastN(klines: unknown[], n: number): number {
    if (!klines?.length) return 0;
    const take = Math.min(n, klines.length);
    const chunk = klines.slice(-take) as Array<unknown[]>;
    return chunk.reduce((s, k) => s + parseFloat(String(k[7] ?? 0)), 0);
  }

  async function fetchKlines7d30d(symbol: string): Promise<{
    qv7: number;
    qv30: number;
    fromCache: boolean;
  }> {
    const hit = loadKlineCache(symbol);
    if (hit) return { qv7: hit.qv7, qv30: hit.qv30, fromCache: true };

    const url = `https://api.binance.com/api/v3/klines?symbol=${encodeURIComponent(
      symbol
    )}&interval=1d&limit=${KLINE_LIMIT}`;
    const res = await fetch(url, { signal: fetchSignal(25000) });
    if (!res.ok) throw new Error(`klines ${symbol} HTTP ${res.status}`);
    const klines = (await res.json()) as unknown[];
    const qv7 = sumQuoteVolLastN(klines, 7);
    const qv30 = sumQuoteVolLastN(klines, 30);
    saveKlineCache(symbol, qv7, qv30);
    return { qv7, qv30, fromCache: false };
  }

  async function tryFetchRankSnapshot(): Promise<RankSnap | null> {
    const url = getRankSnapshotUrl();
    if (!url) return null;
    try {
      const res = await fetch(url, { signal: fetchSignal(20000) });
      if (!res.ok) return null;
      const j = (await res.json()) as RankSnap;
      if (!j || typeof j !== "object" || !j.targets) return null;
      return j;
    } catch (e) {
      if (typeof console !== "undefined" && console.warn) {
        console.warn("[volMon] rank snapshot fetch failed:", e);
      }
      return null;
    }
  }

  function snapshotTimeText(snap: RankSnap | null): string {
    const t = snap?.full_market_cache_updated_at;
    if (t == null || Number.isNaN(Number(t))) return "";
    const d = new Date(Number(t) * 1000);
    return d.toLocaleString("en-US", { timeZone: "Asia/Shanghai" });
  }

  function rankPctDashMsg(snap: RankSnap | null): string {
    if (snap?.mode === "light") {
      return "— (light snapshot: rolling Σ only; run POST /api/vol-snapshot/refresh with {\"mode\":\"full\"} for 7d/30d ranks)";
    }
    return "— (rank snapshot required: ?rankSnapshot= / localStorage / default URL)";
  }

  async function load24hData() {
    const [tickerRes, infoRes] = await Promise.all([
      fetch(TICKER_24HR_URL, { signal: fetchSignal(20000) }),
      fetch(EXCHANGE_INFO_URL, { signal: fetchSignal(20000) }),
    ]);
    if (!tickerRes.ok) throw new Error(`ticker ${tickerRes.status}`);
    if (!infoRes.ok) throw new Error(`exchangeInfo ${infoRes.status}`);

    const raw = (await tickerRes.json()) as Array<{
      symbol: string;
      quoteVolume: string;
    }>;
    const exchangeJson = await infoRes.json();
    const spotSet = buildSpotUsdtSymbolSet(exchangeJson);

    const allUsdt = raw.filter((x) => x.symbol.endsWith("USDT"));
    sortByQuoteVolumeDesc(allUsdt);

    const spotUsdt = raw.filter((x) => spotSet.has(x.symbol));
    sortByQuoteVolumeDesc(spotUsdt);

    state24h = { raw, spotUsdt, allUsdt, updatedAt: Date.now() };
  }

  async function loadWeeklyData() {
    const rankSnap = await tryFetchRankSnapshot();
    const longVolBySymbol: Record<string, LongVol> = {};

    for (let ti = 0; ti < TARGETS.length; ti++) {
      const target = TARGETS[ti];
      const tSnap = rankSnap?.targets?.[target];
      let longVol: LongVol = {
        qv7: null,
        qv30: null,
        longSrc: "—",
        longErr: null,
      };

      if (
        tSnap &&
        tSnap.qv_7d != null &&
        tSnap.qv_30d != null
      ) {
        const st = snapshotTimeText(rankSnap);
        longVol = {
          qv7: tSnap.qv_7d,
          qv30: tSnap.qv_30d,
          rank7: tSnap.rank_7d,
          total7: tSnap.total_7d,
          pct7: tSnap.percentile_7d,
          rank30: tSnap.rank_30d,
          total30: tSnap.total_30d,
          pct30: tSnap.percentile_30d,
          rank24:
            tSnap.rank_24h != null && tSnap.total_24h != null
              ? tSnap.rank_24h
              : undefined,
          total24:
            tSnap.rank_24h != null && tSnap.total_24h != null
              ? tSnap.total_24h
              : undefined,
          pct24:
            tSnap.percentile_24h != null &&
            !Number.isNaN(Number(tSnap.percentile_24h))
              ? Number(tSnap.percentile_24h)
              : undefined,
          longSrc: st
            ? `Rank snapshot (full market ${st})`
            : "Rank snapshot",
          longErr: null,
        };
      } else {
        try {
          const kv = await fetchKlines7d30d(target);
          longVol = {
            qv7: kv.qv7,
            qv30: kv.qv30,
            longSrc: kv.fromCache ? "Local cache" : "Network",
            longErr: null,
          };
        } catch (e) {
          longVol = {
            qv7: null,
            qv30: null,
            longSrc: "—",
            longErr: e instanceof Error ? e.message : String(e),
          };
        }
      }
      longVolBySymbol[target] = longVol;
      if (ti < TARGETS.length - 1) await sleep(KLINES_INTERVAL_MS);
    }

    stateWeekly = {
      longVolBySymbol,
      updatedAt: Date.now(),
      rankSnap,
    };
  }

  function computeSampleNote(): string {
    if (!state24h) return "";
    const { spotUsdt, allUsdt } = state24h;
    const rankSnap = stateWeekly?.rankSnap ?? null;
    const url = getRankSnapshotUrl();
    const urlNote =
      url.length > 72 ? `${url.slice(0, 70)}…` : url;
    const snapHint = rankSnap
      ? rankSnap.mode === "light"
        ? ` Light rank snapshot loaded (7d/30d quote Σ only; no full-market ranks — use full refresh on server). Snapshot time ${snapshotTimeText(rankSnap) || "—"}.`
        : ` Full-market rank snapshot loaded (full-market data time ${snapshotTimeText(rankSnap) || "—"}).`
      : url
        ? " Rank snapshot URL is set but failed to load; 7d/30d shows target quote volume only (no full-market ranks)."
        : " No rank snapshot URL (?rankSnapshot= / localStorage / default). Full-market ranks require the Python snapshot service.";

    return (
      `Universe: spot USDT (exchangeInfo) ${spotUsdt.length} pairs; ` +
      `all *USDT tickers (coarse) ${allUsdt.length}. ` +
      `Snapshot URL: ${urlNote}. ` +
      ` "Refresh 24h" updates ticker only; weekly/monthly auto-refresh every ${WEEKLY_REFRESH_MINUTES} min.` +
      snapHint +
      ` Daily-K localStorage TTL ${KLINE_CACHE_TTL_MS / 60000} min; ${KLINES_INTERVAL_MS} ms between symbol requests.`
    );
  }

  function buildRows(): VolCardRow[] {
    if (!state24h) return [];
    const { raw, spotUsdt, allUsdt } = state24h;
    const longMap = stateWeekly?.longVolBySymbol ?? {};
    const out: VolCardRow[] = [];

    for (const target of TARGETS) {
      const spotStats = rankPercentile(spotUsdt, target);
      const allStats = rankPercentile(allUsdt, target);

      if (!spotStats && !allStats) {
        out.push({
          kind: "missing",
          symbol: target,
          message: "Symbol not in universe",
        });
        continue;
      }

      const row = raw.find((x) => x.symbol === target);
      const volume = row
        ? Math.round(parseFloat(row.quoteVolume)).toLocaleString("en-US")
        : "--";

      const spotWarn = spotStats
        ? bottom20Status(spotStats.percentile).bad
        : false;
      const allWarn = allStats
        ? bottom20Status(allStats.percentile).bad
        : false;
      const cardWarn = spotStats != null ? spotWarn : allWarn;

      const longVol: LongVol = longMap[target] ?? {
        qv7: null,
        qv30: null,
        longSrc: "—",
        longErr: null,
      };

      out.push({
        kind: "card",
        item: {
          symbol: target,
          volume,
          spot: spotStats,
          all: allStats,
          cardWarn,
          longVol,
        },
      });
    }
    return out;
  }

  $: rows = buildRows();
  $: updateLine24h = formatUpdateLine("24h data", state24h?.updatedAt);
  $: updateLineWeekly = formatUpdateLine(
    "Weekly / monthly data",
    stateWeekly?.updatedAt
  );
  $: sampleNote = computeSampleNote();

  function tickCountdowns() {
    const fmt = (ms: number) => {
      const remaining = Math.max(0, Math.round(ms / 1000));
      const m = Math.floor(remaining / 60)
        .toString()
        .padStart(2, "0");
      const s = (remaining % 60).toString().padStart(2, "0");
      return `${m}:${s}`;
    };
    countdownLine24h = `Next auto 24h refresh: ${fmt(
      Math.max(0, next24hAt - Date.now())
    )}`;
    countdownLineWeekly = `Next auto weekly/monthly refresh: ${fmt(
      Math.max(0, nextWeeklyAt - Date.now())
    )}`;
  }

  function schedule24hAuto() {
    if (timer24h) clearTimeout(timer24h);
    next24hAt = Date.now() + AUTO_REFRESH_MINUTES * 60 * 1000;
    timer24h = setTimeout(async () => {
      try {
        await load24hData();
      } catch (e) {
        console.error(e);
      }
      schedule24hAuto();
    }, AUTO_REFRESH_MINUTES * 60 * 1000);
  }

  function scheduleWeeklyAuto() {
    if (timerWeekly) clearTimeout(timerWeekly);
    nextWeeklyAt = Date.now() + WEEKLY_REFRESH_MINUTES * 60 * 1000;
    timerWeekly = setTimeout(async () => {
      try {
        await loadWeeklyData();
      } catch (e) {
        console.error(e);
      }
      scheduleWeeklyAuto();
    }, WEEKLY_REFRESH_MINUTES * 60 * 1000);
  }

  function startCountdownTicker() {
    if (countdownTimer) clearInterval(countdownTimer);
    tickCountdowns();
    countdownTimer = setInterval(tickCountdowns, 1000);
  }

  async function refresh24hOnly() {
    refresh24hBusy = true;
    errorTitle = null;
    errorMsg = null;
    try {
      await load24hData();
      schedule24hAuto();
      startCountdownTicker();
    } catch (err) {
      state24h = null;
      errorTitle = "24h request failed";
      errorMsg = err instanceof Error ? err.message : String(err);
    } finally {
      refresh24hBusy = false;
      loadingInitial = false;
    }
  }

  async function refreshWeeklyOnly() {
    refreshWeeklyBusy = true;
    try {
      await loadWeeklyData();
      scheduleWeeklyAuto();
      startCountdownTicker();
    } catch (e) {
      console.error(e);
    } finally {
      refreshWeeklyBusy = false;
    }
  }

  async function initialLoad() {
    loadingInitial = true;
    errorTitle = null;
    errorMsg = null;
    try {
      await Promise.all([load24hData(), loadWeeklyData()]);
      schedule24hAuto();
      scheduleWeeklyAuto();
      startCountdownTicker();
    } catch (err) {
      state24h = null;
      stateWeekly = null;
      errorTitle = "Request failed";
      errorMsg = err instanceof Error ? err.message : String(err);
    } finally {
      loadingInitial = false;
    }
  }

  onMount(() => {
    initialLoad();
  });

  onDestroy(() => {
    if (timer24h) clearTimeout(timer24h);
    if (timerWeekly) clearTimeout(timerWeekly);
    if (countdownTimer) clearInterval(countdownTimer);
  });
</script>

<section class="bv-wrap" aria-labelledby="bv-heading">
  <h2 id="bv-heading">Binance USDT volume ranks</h2>
  <p class="bv-note">{sampleNote || "—"}</p>
  <div class="bv-meta-block">
    <span class="bv-meta-line">{updateLine24h}</span>
    <span class="bv-meta-line">{updateLineWeekly}</span>
  </div>
  <div class="bv-actions">
    <button
      type="button"
      class="bv-refresh"
      disabled={refresh24hBusy || loadingInitial}
      on:click={refresh24hOnly}
    >
      {refresh24hBusy ? "Refreshing 24h…" : "Refresh 24h (ticker)"}
    </button>
    <button
      type="button"
      class="bv-refresh bv-refresh-secondary"
      disabled={refreshWeeklyBusy || loadingInitial}
      on:click={refreshWeeklyOnly}
    >
      {refreshWeeklyBusy ? "Refreshing weekly/monthly…" : "Refresh weekly/monthly (K-lines / snapshot)"}
    </button>
  </div>
  <div class="bv-countdown-block">
    <span class="bv-countdown-line">{countdownLine24h}</span>
    <span class="bv-countdown-line">{countdownLineWeekly}</span>
  </div>

  {#if loadingInitial && !errorTitle}
    <div class="bv-loading" role="status">
      <span class="bv-spinner" aria-hidden="true"></span>
      Loading…
    </div>
  {:else if errorTitle}
    <div class="bv-card bv-error" role="alert">
      <div class="bv-symbol">❌ {errorTitle}</div>
      <div class="bv-row">
        <span class="bv-label">Error</span>
        <span class="bv-value">{errorMsg}</span>
      </div>
    </div>
  {:else}
    <div class="bv-cards">
      {#each rows as row}
        {#if row.kind === "missing"}
          <div class="bv-card bv-error">
            <div class="bv-symbol">🪙 {row.symbol}</div>
            <div class="bv-row">
              <span class="bv-label">Status</span>
              <span class="bv-value">{row.message}</span>
            </div>
          </div>
        {:else}
          {@const item = row.item}
          {@const lv = item.longVol}
          <div
            class="bv-card"
            class:bv-warn={item.cardWarn}
            class:bv-ok={!item.cardWarn}
          >
            <div class="bv-symbol">🪙 {item.symbol}</div>
            <div class="bv-row">
              <span class="bv-label">24h quote volume</span>
              <span class="bv-value">{item.volume} USDT</span>
            </div>

            {#if !lv.longErr}
              {@const has24Snap =
                lv.rank24 != null && lv.total24 != null}
              {@const pct24Num =
                lv.pct24 != null && !Number.isNaN(Number(lv.pct24))
                  ? Number(lv.pct24)
                  : null}
              {@const st24 = pct24Num != null ? bottom20Status(pct24Num) : null}
              {#if has24Snap}
                <div class="bv-section">24h snapshot (spot USDT universe, server)</div>
                <div class="bv-row">
                  <span class="bv-label">Rank</span>
                  <span class="bv-value">{lv.rank24} / {lv.total24}</span>
                </div>
                <div class="bv-row">
                  <span class="bv-label">Percentile</span>
                  <span class="bv-value"
                    >{pct24Num != null ? fmtPct(pct24Num) : "—"}</span
                  >
                </div>
                <div class="bv-row">
                  <span class="bv-label">Bottom 20%</span>
                  <span
                    class="bv-value"
                    class:bv-status-warn={st24?.bad}
                    class:bv-status-ok={st24 && !st24.bad}>{st24 ? st24.text : "—"}</span
                  >
                </div>
              {/if}
            {/if}

            <div class="bv-section">Weekly / monthly (rolling daily-K quote volume)</div>
            {#if lv.longErr}
              <div class="bv-row">
                <span class="bv-label">K-lines request</span>
                <span class="bv-value bv-status-warn">Failed: {lv.longErr}</span>
              </div>
            {:else}
              {@const pct7Num =
                lv.pct7 != null && !Number.isNaN(Number(lv.pct7))
                  ? Number(lv.pct7)
                  : null}
              {@const pct30Num =
                lv.pct30 != null && !Number.isNaN(Number(lv.pct30))
                  ? Number(lv.pct30)
                  : null}
              {@const st7 = pct7Num != null ? bottom20Status(pct7Num) : null}
              {@const st30 = pct30Num != null ? bottom20Status(pct30Num) : null}
              {@const has7Rank =
                lv.rank7 != null && lv.total7 != null}
              {@const has30Rank =
                lv.rank30 != null && lv.total30 != null}
              {@const rankPctDash = rankPctDashMsg(stateWeekly?.rankSnap ?? null)}
              <div class="bv-row">
                <span class="bv-label">~7d quote Σ</span>
                <span class="bv-value">{fmtUsdt(lv.qv7)} USDT</span>
              </div>
              <div class="bv-row">
                <span class="bv-label">7d full-market rank</span>
                <span class="bv-value"
                  >{has7Rank ? `${lv.rank7} / ${lv.total7}` : rankPctDash}</span
                >
              </div>
              <div class="bv-row">
                <span class="bv-label">7d full-market percentile</span>
                <span class="bv-value"
                  >{pct7Num != null
                    ? fmtPct(pct7Num)
                    : has7Rank
                      ? "—"
                      : rankPctDash}</span
                >
              </div>
              <div class="bv-row">
                <span class="bv-label">7d bottom 20%</span>
                <span
                  class="bv-value"
                  class:bv-status-warn={st7?.bad}
                  class:bv-status-ok={st7 && !st7.bad}>{st7 ? st7.text : "—"}</span
                >
              </div>
              <div class="bv-row">
                <span class="bv-label">~30d quote Σ</span>
                <span class="bv-value">{fmtUsdt(lv.qv30)} USDT</span>
              </div>
              <div class="bv-row">
                <span class="bv-label">30d full-market rank</span>
                <span class="bv-value"
                  >{has30Rank
                    ? `${lv.rank30} / ${lv.total30}`
                    : rankPctDash}</span
                >
              </div>
              <div class="bv-row">
                <span class="bv-label">30d full-market percentile</span>
                <span class="bv-value"
                  >{pct30Num != null
                    ? fmtPct(pct30Num)
                    : has30Rank
                      ? "—"
                      : rankPctDash}</span
                >
              </div>
              <div class="bv-row">
                <span class="bv-label">30d bottom 20%</span>
                <span
                  class="bv-value"
                  class:bv-status-warn={st30?.bad}
                  class:bv-status-ok={st30 && !st30.bad}>{st30 ? st30.text : "—"}</span
                >
              </div>
              <div class="bv-row">
                <span class="bv-label">Data source</span>
                <span class="bv-value">{lv.longSrc || "—"}</span>
              </div>
            {/if}

            <div class="bv-section">Spot USDT (exchangeInfo, Binance-aligned)</div>
            {#if item.spot}
              {@const st = bottom20Status(item.spot.percentile)}
              <div class="bv-row">
                <span class="bv-label">Rank</span>
                <span class="bv-value"
                  >{item.spot.rank} / {item.spot.total}</span
                >
              </div>
              <div class="bv-row">
                <span class="bv-label">Percentile</span>
                <span class="bv-value">{fmtPct(item.spot.percentile)}</span>
              </div>
              <div class="bv-row">
                <span class="bv-label">Bottom 20%</span>
                <span
                  class="bv-value"
                  class:bv-status-warn={st.bad}
                  class:bv-status-ok={!st.bad}>{st.text}</span
                >
              </div>
            {:else}
              <div class="bv-row">
                <span class="bv-label">Rank / percentile</span>
                <span class="bv-value">— (not in this universe)</span>
              </div>
            {/if}

            <div class="bv-section">All *USDT tickers (coarse filter)</div>
            {#if item.all}
              {@const st2 = bottom20Status(item.all.percentile)}
              <div class="bv-row">
                <span class="bv-label">Rank</span>
                <span class="bv-value"
                  >{item.all.rank} / {item.all.total}</span
                >
              </div>
              <div class="bv-row">
                <span class="bv-label">Percentile</span>
                <span class="bv-value">{fmtPct(item.all.percentile)}</span>
              </div>
              <div class="bv-row">
                <span class="bv-label">Bottom 20%</span>
                <span
                  class="bv-value"
                  class:bv-status-warn={st2.bad}
                  class:bv-status-ok={!st2.bad}>{st2.text}</span
                >
              </div>
            {:else}
              <div class="bv-row">
                <span class="bv-label">Rank / percentile</span>
                <span class="bv-value">— (not in this universe)</span>
              </div>
            {/if}

            <p class="bv-footnote">
              Card highlight: based on whether the symbol is in the bottom 20% of the spot-USDT 24h
              universe; if not in spot sample, the all-*USDT coarse universe is used instead.
              Weekly/monthly full-market rank and percentile match the rolling ~N-day quote Σ and come
              from the Python rank snapshot (configured URL); they differ from the 24h ticker ranking.
            </p>
          </div>
        {/if}
      {/each}
    </div>
  {/if}
</section>

<style>
  .bv-wrap {
    width: 100%;
    max-width: 960px;
    margin: 2.5rem auto 0;
    padding: 1.25rem 1rem 2rem;
    border-top: 1px solid #ddd;
    box-sizing: border-box;
  }

  .bv-wrap h2 {
    font-size: 1.25rem;
    font-weight: 600;
    color: #222;
    margin: 0 0 0.5rem;
    text-align: center;
  }

  .bv-note {
    font-size: 0.82rem;
    color: #666;
    line-height: 1.45;
    text-align: center;
    margin: 0 auto 0.5rem;
    max-width: 40rem;
  }

  .bv-meta-block {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.2rem;
    margin-bottom: 0.75rem;
  }

  .bv-meta-line {
    font-size: 0.85rem;
    color: #888;
    text-align: center;
    line-height: 1.45;
  }

  .bv-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem 0.75rem;
    justify-content: center;
    margin-bottom: 0.5rem;
  }

  .bv-refresh {
    padding: 0.45em 1.1em;
    background: #2d6a4f;
    color: #fff;
    border: 1px solid #1b4332;
    border-radius: 6px;
    cursor: pointer;
    font-size: 0.92rem;
  }

  .bv-refresh-secondary {
    background: #1d4ed8;
    border-color: #1e40af;
  }

  .bv-refresh-secondary:hover:not(:disabled) {
    background: #2563eb;
  }

  .bv-refresh:hover:not(:disabled) {
    background: #40916c;
  }

  .bv-refresh:disabled {
    opacity: 0.65;
    cursor: not-allowed;
  }

  .bv-countdown-block {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.2rem;
    margin-bottom: 1.25rem;
  }

  .bv-countdown-line {
    font-size: 0.82rem;
    color: #888;
    text-align: center;
    line-height: 1.45;
  }

  .bv-loading {
    text-align: center;
    color: #666;
    padding: 2rem 0;
  }

  .bv-spinner {
    display: inline-block;
    width: 18px;
    height: 18px;
    border: 3px solid #ccc;
    border-top-color: #2d6a4f;
    border-radius: 50%;
    animation: bv-spin 0.7s linear infinite;
    vertical-align: middle;
    margin-right: 8px;
  }

  @keyframes bv-spin {
    to {
      transform: rotate(360deg);
    }
  }

  .bv-cards {
    display: flex;
    flex-wrap: wrap;
    gap: 1.25rem;
    justify-content: center;
  }

  .bv-card {
    background: #fafafa;
    border: 1px solid #ddd;
    border-radius: 8px;
    padding: 1.1rem 1.25rem;
    min-width: 240px;
    flex: 1;
    max-width: 400px;
    box-sizing: border-box;
  }

  .bv-card.bv-ok {
    border-color: #95d5b2;
    background: #f0fdf4;
  }

  .bv-card.bv-warn {
    border-color: #e9c46a;
    background: #fffbeb;
  }

  .bv-card.bv-error {
    border-color: #e07a7a;
    background: #fff5f5;
    color: #8b1538;
  }

  .bv-symbol {
    font-size: 1.1rem;
    font-weight: 600;
    margin-bottom: 0.75rem;
    letter-spacing: 0.02em;
    color: #222;
  }

  .bv-error .bv-symbol {
    color: #8b1538;
  }

  .bv-row {
    display: flex;
    justify-content: space-between;
    gap: 0.75rem;
    padding: 0.35rem 0;
    border-bottom: 1px solid #e8e8e8;
    font-size: 0.92rem;
  }

  .bv-row:last-of-type {
    border-bottom: none;
  }

  .bv-label {
    color: #666;
    flex-shrink: 0;
  }

  .bv-value {
    color: #222;
    font-weight: 500;
    text-align: right;
  }

  .bv-status-warn {
    color: #b45309;
    font-weight: 600;
  }

  .bv-status-ok {
    color: #166534;
    font-weight: 600;
  }

  .bv-section {
    margin-top: 0.85rem;
    padding-top: 0.5rem;
    border-top: 1px solid #e0e0e0;
    font-size: 0.78rem;
    color: #777;
    letter-spacing: 0.02em;
  }

  .bv-footnote {
    margin: 0.85rem 0 0;
    padding-top: 0.65rem;
    border-top: 1px solid #e8e8e8;
    font-size: 0.75rem;
    color: #888;
    line-height: 1.4;
  }
</style>
