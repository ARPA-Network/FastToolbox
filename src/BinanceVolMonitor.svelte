<script lang="ts">
  import { onDestroy, onMount } from "svelte";

  const TARGETS = ["ARPAUSDT", "BELUSDT"] as const;
  const AUTO_REFRESH_MINUTES = 30;
  const EXCHANGE_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo";
  const TICKER_24HR_URL = "https://api.binance.com/api/v3/ticker/24hr";

  type RankInfo = {
    rank: number;
    total: number;
    percentile: number;
  };

  type VolCard = {
    symbol: string;
    volume: string;
    spot: RankInfo | null;
    all: RankInfo | null;
    cardWarn: boolean;
  };

  type VolCardRow =
    | { kind: "card"; item: VolCard }
    | { kind: "missing"; symbol: string; message: string };

  let sampleNote = "";
  let updateTime = "";
  let countdownText = "";
  let loading = true;
  let refreshBusy = false;
  let errorTitle: string | null = null;
  let errorMsg: string | null = null;
  let rows: VolCardRow[] = [];

  let countdownTimer: ReturnType<typeof setInterval> | null = null;
  let autoRefreshTimer: ReturnType<typeof setTimeout> | null = null;
  let nextRefreshAt = 0;

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
    rows: Array<{ quoteVolume: string; symbol: string }>
  ) {
    rows.sort(
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
      text: bad ? "⚠️ 倒数20%！" : "✅ 正常(不在倒数20%)",
    };
  }

  function fmtPct(p: number) {
    return (p * 100).toFixed(2) + "%";
  }

  function resetAutoRefresh() {
    if (autoRefreshTimer) clearTimeout(autoRefreshTimer);
    if (countdownTimer) clearInterval(countdownTimer);

    nextRefreshAt = Date.now() + AUTO_REFRESH_MINUTES * 60 * 1000;

    autoRefreshTimer = setTimeout(
      fetchData,
      AUTO_REFRESH_MINUTES * 60 * 1000
    );

    countdownTimer = setInterval(() => {
      const remaining = Math.max(
        0,
        Math.round((nextRefreshAt - Date.now()) / 1000)
      );
      const m = Math.floor(remaining / 60)
        .toString()
        .padStart(2, "0");
      const s = (remaining % 60).toString().padStart(2, "0");
      countdownText = `距离自动刷新还有 ${m}:${s}`;
    }, 1000);
  }

  async function fetchData() {
    refreshBusy = true;
    loading = true;
    errorTitle = null;
    errorMsg = null;

    try {
      const [tickerRes, infoRes] = await Promise.all([
        fetch(TICKER_24HR_URL, { signal: AbortSignal.timeout(20000) }),
        fetch(EXCHANGE_INFO_URL, { signal: AbortSignal.timeout(20000) }),
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

      sampleNote =
        `样本口径：现货 USDT（exchangeInfo，与官网一致）${spotUsdt.length} 个；` +
        `全部 USDT 后缀（ticker 粗筛）${allUsdt.length} 个。`;

      const nextRows: VolCardRow[] = [];

      for (const target of TARGETS) {
        const spotStats = rankPercentile(spotUsdt, target);
        const allStats = rankPercentile(allUsdt, target);

        if (!spotStats && !allStats) {
          nextRows.push({
            kind: "missing",
            symbol: target,
            message: "交易对不存在",
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

        nextRows.push({
          kind: "card",
          item: {
            symbol: target,
            volume,
            spot: spotStats,
            all: allStats,
            cardWarn,
          },
        });
      }

      rows = nextRows;
      updateTime = `最后更新：${new Date().toLocaleString("zh-CN", {
        timeZone: "Asia/Shanghai",
      })}`;
    } catch (err) {
      sampleNote = "";
      rows = [];
      errorTitle = "请求失败";
      errorMsg = err instanceof Error ? err.message : String(err);
    } finally {
      loading = false;
      refreshBusy = false;
      resetAutoRefresh();
    }
  }

  onMount(() => {
    fetchData();
  });

  onDestroy(() => {
    if (autoRefreshTimer) clearTimeout(autoRefreshTimer);
    if (countdownTimer) clearInterval(countdownTimer);
  });
</script>

<section class="bv-wrap" aria-labelledby="bv-heading">
  <h2 id="bv-heading">币安 USDT 交易量排名</h2>
  <p class="bv-note">{sampleNote || "—"}</p>
  <p class="bv-meta">{updateTime || "—"}</p>
  <button
    type="button"
    class="bv-refresh"
    disabled={refreshBusy}
    on:click={fetchData}
  >
    {refreshBusy ? "加载中…" : "立即刷新"}
  </button>
  <p class="bv-countdown">{countdownText}</p>

  {#if loading && rows.length === 0 && !errorTitle}
    <div class="bv-loading" role="status">
      <span class="bv-spinner" aria-hidden="true"></span>
      正在加载…
    </div>
  {:else if errorTitle}
    <div class="bv-card bv-error" role="alert">
      <div class="bv-symbol">❌ {errorTitle}</div>
      <div class="bv-row">
        <span class="bv-label">错误信息</span>
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
              <span class="bv-label">状态</span>
              <span class="bv-value">{row.message}</span>
            </div>
          </div>
        {:else}
          {@const item = row.item}
          <div
            class="bv-card"
            class:bv-warn={item.cardWarn}
            class:bv-ok={!item.cardWarn}
          >
            <div class="bv-symbol">🪙 {item.symbol}</div>
            <div class="bv-row">
              <span class="bv-label">24h 成交额</span>
              <span class="bv-value">{item.volume} USDT</span>
            </div>

            <div class="bv-section">现货 USDT（exchangeInfo，与官网一致）</div>
            {#if item.spot}
              {@const st = bottom20Status(item.spot.percentile)}
              <div class="bv-row">
                <span class="bv-label">排名</span>
                <span class="bv-value"
                  >{item.spot.rank} / {item.spot.total}</span
                >
              </div>
              <div class="bv-row">
                <span class="bv-label">百分位</span>
                <span class="bv-value">{fmtPct(item.spot.percentile)}</span>
              </div>
              <div class="bv-row">
                <span class="bv-label">倒数20%</span>
                <span
                  class="bv-value"
                  class:bv-status-warn={st.bad}
                  class:bv-status-ok={!st.bad}>{st.text}</span
                >
              </div>
            {:else}
              <div class="bv-row">
                <span class="bv-label">排名 / 百分位</span>
                <span class="bv-value">—（不在该样本中）</span>
              </div>
            {/if}

            <div class="bv-section">全部 USDT 后缀（ticker 粗筛）</div>
            {#if item.all}
              {@const st2 = bottom20Status(item.all.percentile)}
              <div class="bv-row">
                <span class="bv-label">排名</span>
                <span class="bv-value"
                  >{item.all.rank} / {item.all.total}</span
                >
              </div>
              <div class="bv-row">
                <span class="bv-label">百分位</span>
                <span class="bv-value">{fmtPct(item.all.percentile)}</span>
              </div>
              <div class="bv-row">
                <span class="bv-label">倒数20%</span>
                <span
                  class="bv-value"
                  class:bv-status-warn={st2.bad}
                  class:bv-status-ok={!st2.bad}>{st2.text}</span
                >
              </div>
            {:else}
              <div class="bv-row">
                <span class="bv-label">排名 / 百分位</span>
                <span class="bv-value">—（不在该样本中）</span>
              </div>
            {/if}

            <p class="bv-footnote">
              卡片高亮：以「现货 USDT」样本是否处于倒数20%为准；若无现货样本则看全部后缀。
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
    margin: 0 auto 0.35rem;
    max-width: 36rem;
  }

  .bv-meta {
    font-size: 0.85rem;
    color: #888;
    text-align: center;
    margin: 0 0 0.75rem;
  }

  .bv-refresh {
    display: block;
    margin: 0 auto 0.5rem;
    padding: 0.45em 1.25em;
    background: #2d6a4f;
    color: #fff;
    border: 1px solid #1b4332;
    border-radius: 6px;
    cursor: pointer;
  }

  .bv-refresh:hover:not(:disabled) {
    background: #40916c;
  }

  .bv-refresh:disabled {
    opacity: 0.65;
    cursor: not-allowed;
  }

  .bv-countdown {
    font-size: 0.82rem;
    color: #888;
    text-align: center;
    margin: 0 0 1.25rem;
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
