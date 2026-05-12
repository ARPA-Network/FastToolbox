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

  type Bottom20 = { bad: boolean; text: string };

  /** Precomputed in `buildRows` so the `{#each}` branch needs no `{@const}` (avoids fragile nested-const + each rendering). */
  type VolCardDisp = {
    has24Snap: boolean;
    pct24Num: number | null;
    st24: Bottom20 | null;
    pct7Num: number | null;
    pct30Num: number | null;
    st7: Bottom20 | null;
    st30: Bottom20 | null;
    has7Rank: boolean;
    has30Rank: boolean;
    rankPctDash: string;
    spotSt: Bottom20 | null;
    allSt: Bottom20 | null;
  };

  type VolCard = {
    symbol: string;
    volume: string;
    spot: RankInfo | null;
    all: RankInfo | null;
    cardWarn: boolean;
    longVol: LongVol;
    disp: VolCardDisp;
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
  let pairRows: VolCardRow[] = [];

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

  function buildVolCardDisp(
    lv: LongVol,
    rankSnap: RankSnap | null
  ): VolCardDisp {
    const pct24Num =
      lv.pct24 != null && !Number.isNaN(Number(lv.pct24))
        ? Number(lv.pct24)
        : null;
    const pct7Num =
      lv.pct7 != null && !Number.isNaN(Number(lv.pct7))
        ? Number(lv.pct7)
        : null;
    const pct30Num =
      lv.pct30 != null && !Number.isNaN(Number(lv.pct30))
        ? Number(lv.pct30)
        : null;
    return {
      has24Snap: lv.rank24 != null && lv.total24 != null,
      pct24Num,
      st24: pct24Num != null ? bottom20Status(pct24Num) : null,
      pct7Num,
      pct30Num,
      st7: pct7Num != null ? bottom20Status(pct7Num) : null,
      st30: pct30Num != null ? bottom20Status(pct30Num) : null,
      has7Rank: lv.rank7 != null && lv.total7 != null,
      has30Rank: lv.rank30 != null && lv.total30 != null,
      rankPctDash: rankPctDashMsg(rankSnap),
      spotSt: null,
      allSt: null,
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

      const disp = buildVolCardDisp(longVol, stateWeekly?.rankSnap ?? null);
      disp.spotSt = spotStats ? bottom20Status(spotStats.percentile) : null;
      disp.allSt = allStats ? bottom20Status(allStats.percentile) : null;

      out.push({
        kind: "card",
        item: {
          symbol: target,
          volume,
          spot: spotStats,
          all: allStats,
          cardWarn,
          longVol,
          disp,
        },
      });
    }
    return out;
  }

  $: {
    state24h;
    stateWeekly;
    pairRows = buildRows();
  }
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
  <div class="bv-hero">
    <p class="bv-eyebrow">Market structure</p>
    <h2 id="bv-heading">Binance USDT volume ranks</h2>
    <p class="bv-tagline">24h ticker · rolling 7d/30d Σ · snapshot percentiles</p>
  </div>
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
      {#each pairRows as row}
        {#if row.kind === "missing"}
          <div class="bv-card bv-error">
            <div class="bv-symbol">🪙 {row.symbol}</div>
            <div class="bv-row">
              <span class="bv-label">Status</span>
              <span class="bv-value">{row.message}</span>
            </div>
          </div>
        {:else}
          <div
            class="bv-card"
            class:bv-warn={row.item.cardWarn}
            class:bv-ok={!row.item.cardWarn}
          >
            <div class="bv-symbol">🪙 {row.item.symbol}</div>
            <div class="bv-row">
              <span class="bv-label">24h quote volume</span>
              <span class="bv-value">{row.item.volume} USDT</span>
            </div>

            {#if !row.item.longVol.longErr}
              {#if row.item.disp.has24Snap}
                <div class="bv-section">24h snapshot (spot USDT universe, server)</div>
                <div class="bv-row">
                  <span class="bv-label">Rank</span>
                  <span class="bv-value"
                    >{row.item.longVol.rank24} / {row.item.longVol.total24}</span
                  >
                </div>
                <div class="bv-row">
                  <span class="bv-label">Percentile</span>
                  <span class="bv-value"
                    >{row.item.disp.pct24Num != null
                      ? fmtPct(row.item.disp.pct24Num)
                      : "—"}</span
                  >
                </div>
                <div class="bv-row">
                  <span class="bv-label">Bottom 20%</span>
                  <span
                    class="bv-value"
                    class:bv-status-warn={row.item.disp.st24?.bad}
                    class:bv-status-ok={row.item.disp.st24 && !row.item.disp.st24.bad}
                    >{row.item.disp.st24 ? row.item.disp.st24.text : "—"}</span
                  >
                </div>
              {/if}
            {/if}

            <div class="bv-section">Weekly / monthly (rolling daily-K quote volume)</div>
            {#if row.item.longVol.longErr}
              <div class="bv-row">
                <span class="bv-label">K-lines request</span>
                <span class="bv-value bv-status-warn"
                  >Failed: {row.item.longVol.longErr}</span
                >
              </div>
            {:else}
              <div class="bv-row">
                <span class="bv-label">~7d quote Σ</span>
                <span class="bv-value"
                  >{fmtUsdt(row.item.longVol.qv7)} USDT</span
                >
              </div>
              <div class="bv-row">
                <span class="bv-label">7d full-market rank</span>
                <span class="bv-value"
                  >{row.item.disp.has7Rank
                    ? `${row.item.longVol.rank7} / ${row.item.longVol.total7}`
                    : row.item.disp.rankPctDash}</span
                >
              </div>
              <div class="bv-row">
                <span class="bv-label">7d full-market percentile</span>
                <span class="bv-value"
                  >{row.item.disp.pct7Num != null
                    ? fmtPct(row.item.disp.pct7Num)
                    : row.item.disp.has7Rank
                      ? "—"
                      : row.item.disp.rankPctDash}</span
                >
              </div>
              <div class="bv-row">
                <span class="bv-label">7d bottom 20%</span>
                <span
                  class="bv-value"
                  class:bv-status-warn={row.item.disp.st7?.bad}
                  class:bv-status-ok={row.item.disp.st7 && !row.item.disp.st7.bad}
                  >{row.item.disp.st7 ? row.item.disp.st7.text : "—"}</span
                >
              </div>
              <div class="bv-row">
                <span class="bv-label">~30d quote Σ</span>
                <span class="bv-value"
                  >{fmtUsdt(row.item.longVol.qv30)} USDT</span
                >
              </div>
              <div class="bv-row">
                <span class="bv-label">30d full-market rank</span>
                <span class="bv-value"
                  >{row.item.disp.has30Rank
                    ? `${row.item.longVol.rank30} / ${row.item.longVol.total30}`
                    : row.item.disp.rankPctDash}</span
                >
              </div>
              <div class="bv-row">
                <span class="bv-label">30d full-market percentile</span>
                <span class="bv-value"
                  >{row.item.disp.pct30Num != null
                    ? fmtPct(row.item.disp.pct30Num)
                    : row.item.disp.has30Rank
                      ? "—"
                      : row.item.disp.rankPctDash}</span
                >
              </div>
              <div class="bv-row">
                <span class="bv-label">30d bottom 20%</span>
                <span
                  class="bv-value"
                  class:bv-status-warn={row.item.disp.st30?.bad}
                  class:bv-status-ok={row.item.disp.st30 && !row.item.disp.st30.bad}
                  >{row.item.disp.st30 ? row.item.disp.st30.text : "—"}</span
                >
              </div>
              <div class="bv-row">
                <span class="bv-label">Data source</span>
                <span class="bv-value">{row.item.longVol.longSrc || "—"}</span>
              </div>
            {/if}

            <div class="bv-section">Spot USDT (exchangeInfo, Binance-aligned)</div>
            {#if row.item.spot}
              <div class="bv-row">
                <span class="bv-label">Rank</span>
                <span class="bv-value"
                  >{row.item.spot.rank} / {row.item.spot.total}</span
                >
              </div>
              <div class="bv-row">
                <span class="bv-label">Percentile</span>
                <span class="bv-value">{fmtPct(row.item.spot.percentile)}</span>
              </div>
              <div class="bv-row">
                <span class="bv-label">Bottom 20%</span>
                <span
                  class="bv-value"
                  class:bv-status-warn={row.item.disp.spotSt?.bad}
                  class:bv-status-ok={row.item.disp.spotSt && !row.item.disp.spotSt.bad}
                  >{row.item.disp.spotSt ? row.item.disp.spotSt.text : "—"}</span
                >
              </div>
            {:else}
              <div class="bv-row">
                <span class="bv-label">Rank / percentile</span>
                <span class="bv-value">— (not in this universe)</span>
              </div>
            {/if}

            <div class="bv-section">All *USDT tickers (coarse filter)</div>
            {#if row.item.all}
              <div class="bv-row">
                <span class="bv-label">Rank</span>
                <span class="bv-value"
                  >{row.item.all.rank} / {row.item.all.total}</span
                >
              </div>
              <div class="bv-row">
                <span class="bv-label">Percentile</span>
                <span class="bv-value">{fmtPct(row.item.all.percentile)}</span>
              </div>
              <div class="bv-row">
                <span class="bv-label">Bottom 20%</span>
                <span
                  class="bv-value"
                  class:bv-status-warn={row.item.disp.allSt?.bad}
                  class:bv-status-ok={row.item.disp.allSt && !row.item.disp.allSt.bad}
                  >{row.item.disp.allSt ? row.item.disp.allSt.text : "—"}</span
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
  /* Align with App `ft-panel`: same surface, radius, shadow — no ivory “paper” cards */
  .bv-wrap {
    width: 100%;
    max-width: 1080px;
    margin: 2rem auto 2.75rem;
    padding: 1.5rem 1.35rem 1.75rem;
    box-sizing: border-box;
    border-radius: var(--ft-radius, 14px);
    border: 1px solid var(--ft-line, rgba(255, 255, 255, 0.06));
    background: linear-gradient(
      160deg,
      rgba(28, 32, 41, 0.92) 0%,
      rgba(18, 20, 26, 0.96) 100%
    );
    box-shadow: var(--ft-shadow, 0 20px 50px rgba(0, 0, 0, 0.45));
    position: relative;
    overflow: hidden;
  }

  .bv-wrap::before {
    content: "";
    position: absolute;
    inset: 0 0 auto 0;
    height: 3px;
    background: linear-gradient(
      90deg,
      transparent,
      rgba(201, 169, 98, 0.25),
      transparent
    );
    opacity: 0.9;
    pointer-events: none;
  }

  .bv-hero {
    text-align: center;
    margin-bottom: 1rem;
  }

  .bv-eyebrow {
    font-size: 0.65rem;
    font-weight: 600;
    letter-spacing: 0.26em;
    text-transform: uppercase;
    color: var(--ft-accent, #c9a962);
    margin: 0 0 0.4rem;
  }

  .bv-wrap h2 {
    font-family: var(--ft-font-display, "Cormorant", Georgia, serif);
    font-size: clamp(1.65rem, 3.5vw, 2.15rem);
    font-weight: 600;
    letter-spacing: 0.04em;
    color: var(--ft-text, #e9e6e1);
    margin: 0 0 0.35rem;
    line-height: 1.15;
  }

  .bv-tagline {
    margin: 0;
    font-size: 0.8rem;
    font-weight: 300;
    color: var(--ft-text-soft, #a39e96);
    letter-spacing: 0.06em;
  }

  .bv-note {
    font-size: 0.78rem;
    color: var(--ft-muted, #6d6860);
    line-height: 1.55;
    text-align: center;
    margin: 0 auto 1rem;
    max-width: 44rem;
    padding: 0.65rem 0.75rem;
    border-radius: var(--ft-radius-sm, 10px);
    background: rgba(0, 0, 0, 0.28);
    border: 1px solid var(--ft-line, rgba(255, 255, 255, 0.06));
  }

  .bv-meta-block {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.35rem;
    margin-bottom: 1rem;
  }

  .bv-meta-line {
    font-size: 0.78rem;
    color: var(--ft-text-soft, #a39e96);
    text-align: center;
    line-height: 1.45;
    font-variant-numeric: tabular-nums;
  }

  .bv-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.65rem 0.85rem;
    justify-content: center;
    margin-bottom: 0.65rem;
  }

  .bv-refresh {
    padding: 0.62rem 1.25rem;
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    border-radius: 999px;
    cursor: pointer;
    border: 1px solid var(--ft-line-strong, rgba(255, 255, 255, 0.12));
    background: linear-gradient(165deg, #1e2620 0%, #141a16 100%);
    color: var(--ft-text, #e9e6e1);
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.25);
    transition:
      transform 0.12s ease,
      box-shadow 0.18s ease,
      border-color 0.18s ease;
  }

  .bv-refresh-secondary {
    border-color: var(--ft-line-strong, rgba(255, 255, 255, 0.12));
    background: linear-gradient(165deg, #222630 0%, #171a22 100%);
    color: var(--ft-text, #e9e6e1);
  }

  .bv-refresh-secondary:hover:not(:disabled) {
    border-color: rgba(201, 169, 98, 0.35);
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.35);
  }

  .bv-refresh:hover:not(:disabled) {
    transform: translateY(-1px);
    border-color: rgba(201, 169, 98, 0.4);
    box-shadow: 0 6px 22px rgba(0, 0, 0, 0.38);
  }

  .bv-refresh:disabled {
    opacity: 0.45;
    cursor: not-allowed;
    transform: none;
  }

  .bv-countdown-block {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.25rem;
    margin-bottom: 1.5rem;
    padding-bottom: 0.25rem;
  }

  .bv-countdown-line {
    font-size: 0.72rem;
    color: var(--ft-muted, #6d6860);
    text-align: center;
    line-height: 1.45;
    font-variant-numeric: tabular-nums;
    letter-spacing: 0.04em;
  }

  .bv-loading {
    text-align: center;
    color: var(--ft-text-soft, #a39e96);
    padding: 2.5rem 0;
    font-size: 0.9rem;
    font-weight: 300;
    letter-spacing: 0.08em;
  }

  .bv-spinner {
    display: inline-block;
    width: 20px;
    height: 20px;
    border: 2px solid rgba(255, 255, 255, 0.12);
    border-top-color: var(--ft-accent, #c9a962);
    border-radius: 50%;
    animation: bv-spin 0.75s linear infinite;
    vertical-align: middle;
    margin-right: 10px;
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
    align-items: stretch;
  }

  .bv-card {
    background: rgba(0, 0, 0, 0.22);
    border: 1px solid var(--ft-line, rgba(255, 255, 255, 0.06));
    border-radius: var(--ft-radius, 14px);
    padding: 1.25rem 1.3rem 1.15rem;
    min-width: 260px;
    flex: 1;
    max-width: 420px;
    box-sizing: border-box;
    box-shadow: 0 1px 0 rgba(255, 255, 255, 0.04) inset;
    color: var(--ft-text, #e9e6e1);
    position: relative;
    transition:
      border-color 0.18s ease,
      box-shadow 0.18s ease;
  }

  .bv-card:hover {
    border-color: var(--ft-line-strong, rgba(255, 255, 255, 0.12));
    box-shadow:
      0 1px 0 rgba(255, 255, 255, 0.05) inset,
      0 12px 28px rgba(0, 0, 0, 0.25);
  }

  .bv-card.bv-ok {
    border-color: rgba(74, 222, 128, 0.2);
    box-shadow:
      0 1px 0 rgba(255, 255, 255, 0.04) inset,
      0 0 0 1px rgba(74, 222, 128, 0.08);
  }

  .bv-card.bv-ok::after {
    content: "";
    position: absolute;
    left: 0;
    top: 14%;
    bottom: 14%;
    width: 3px;
    border-radius: 0 3px 3px 0;
    background: linear-gradient(180deg, #4ade80, #16a34a);
    opacity: 0.75;
  }

  .bv-card.bv-warn {
    border-color: rgba(250, 204, 21, 0.28);
    box-shadow:
      0 1px 0 rgba(255, 255, 255, 0.04) inset,
      0 0 0 1px rgba(250, 204, 21, 0.1);
  }

  .bv-card.bv-warn::after {
    content: "";
    position: absolute;
    left: 0;
    top: 14%;
    bottom: 14%;
    width: 3px;
    border-radius: 0 3px 3px 0;
    background: linear-gradient(180deg, #facc15, #ca8a04);
    opacity: 0.85;
  }

  .bv-card.bv-error {
    background: rgba(40, 18, 22, 0.55);
    border-color: rgba(248, 113, 113, 0.25);
    color: #fce7e9;
    box-shadow: 0 12px 28px rgba(0, 0, 0, 0.35);
  }

  .bv-card.bv-error:hover {
    transform: none;
  }

  .bv-symbol {
    font-family: var(--ft-font-ui, "Sora", sans-serif);
    font-size: 0.95rem;
    font-weight: 600;
    margin-bottom: 0.75rem;
    letter-spacing: 0.08em;
    color: var(--ft-text, #e9e6e1);
    font-variant-numeric: tabular-nums;
  }

  .bv-card.bv-error .bv-symbol {
    color: #fecaca;
  }

  .bv-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 0.75rem;
    padding: 0.4rem 0;
    border-bottom: 1px solid var(--ft-line, rgba(255, 255, 255, 0.06));
    font-size: 0.84rem;
  }

  .bv-card.bv-error .bv-row {
    border-bottom-color: rgba(255, 255, 255, 0.1);
  }

  .bv-row:last-of-type {
    border-bottom: none;
  }

  .bv-label {
    color: var(--ft-text-soft, #a39e96);
    flex-shrink: 0;
    font-size: 0.76rem;
    font-weight: 500;
    letter-spacing: 0.03em;
  }

  .bv-card.bv-error .bv-label {
    color: rgba(255, 255, 255, 0.55);
  }

  .bv-value {
    color: var(--ft-text, #e9e6e1);
    font-weight: 500;
    text-align: right;
    font-variant-numeric: tabular-nums;
    font-feature-settings: "tnum" 1;
    letter-spacing: 0.02em;
  }

  .bv-card.bv-error .bv-value {
    color: #fde8ec;
  }

  .bv-status-warn {
    color: #fbbf24;
    font-weight: 600;
  }

  .bv-status-ok {
    color: #86efac;
    font-weight: 600;
  }

  .bv-section {
    margin-top: 0.95rem;
    padding-top: 0.5rem;
    border-top: 1px solid var(--ft-line, rgba(255, 255, 255, 0.06));
    font-size: 0.65rem;
    font-weight: 600;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: var(--ft-muted, #6d6860);
  }

  .bv-footnote {
    margin: 1rem 0 0;
    padding-top: 0.75rem;
    border-top: 1px solid var(--ft-line, rgba(255, 255, 255, 0.06));
    font-size: 0.68rem;
    color: var(--ft-muted, #6d6860);
    line-height: 1.45;
    font-weight: 400;
  }
</style>
