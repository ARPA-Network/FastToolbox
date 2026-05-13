<script lang="ts">
  import { decToBin, decToHex, hexToBin, hexToDec } from "./converter.js";
  import { DateInput } from "date-picker-svelte";
  import BinanceVolMonitor from "./BinanceVolMonitor.svelte";

  let decimal1: string;
  let binary1;
  let hex1;
  let hex2: string;
  let binary2;
  let decimal2;
  let date1 = new Date();
  let arpaCurrentPrice;
  let arpaHistoricalPrice;
  let date2 = new Date();
  let belCurrentPrice;
  let belHistoricalPrice;

  function handleDecimalInput() {
    binary1 = decToBin(decimal1);
    hex1 = decToHex(decimal1);
  }

  function handleHexInput() {
    binary2 = hexToBin(hex2);
    decimal2 = hexToDec(hex2);
  }

  function formatDate(date, fmt) {
    if (typeof date == "string") {
      return date;
    }

    if (!fmt) fmt = "yyyy-MM-dd hh:mm:ss";

    if (!date || date == null) return null;
    var o = {
      "M+": date.getMonth() + 1,
      "d+": date.getDate(),
      "h+": date.getHours(),
      "m+": date.getMinutes(),
      "s+": date.getSeconds(),
      "q+": Math.floor((date.getMonth() + 3) / 3),
      S: date.getMilliseconds(),
    };
    if (/(y+)/.test(fmt))
      fmt = fmt.replace(
        RegExp.$1,
        (date.getFullYear() + "").substring(4 - RegExp.$1.length)
      );
    for (var k in o) {
      if (new RegExp("(" + k + ")").test(fmt))
        fmt = fmt.replace(
          RegExp.$1,
          RegExp.$1.length === 1
            ? o[k]
            : ("00" + o[k]).substring(("" + o[k]).length)
        );
    }
    return fmt;
  }

  /** CoinGecko blocks browser CORS; production uses Vercel `/api/*` proxies. */
  function getCurrentPrice(token) {
    const q = new URLSearchParams({
      ids: token,
      vs_currencies: "usd",
    });
    fetch(`/api/coingecko-simple-price?${q}`)
      .then((response) => response.json())
      .then((data) => {
        if (token === "bella-protocol")
          belCurrentPrice = data["bella-protocol"].usd;
        else arpaCurrentPrice = data.arpa.usd;
      })
      .catch(() => {});
  }

  function getHistoricalPrice(token, date) {
    const q = new URLSearchParams({ id: token, date });
    fetch(`/api/coingecko-history?${q}`)
      .then((response) => response.json())
      .then((data) => {
        if (token === "bella-protocol")
          belHistoricalPrice = data.market_data.current_price.usd;
        else arpaHistoricalPrice = data.market_data.current_price.usd;
      })
      .catch(() => {});
  }

  type FtTab = "volume" | "radix" | "prices";

  let activeTab: FtTab = "volume";

  const tabs: { id: FtTab; label: string; desc: string }[] = [
    { id: "volume", label: "Binance volume", desc: "Spot USDT ranks & snapshots" },
    { id: "radix", label: "Radix", desc: "Decimal · binary · hex" },
    { id: "prices", label: "Token prices", desc: "ARPA & BEL via CoinGecko proxy" },
  ];
</script>

<svelte:head>
  <title>FastToolbox</title>
  <meta name="robots" content="noindex, nofollow" />
  <html lang="en" />
</svelte:head>

<div class="ft-app">
  <header class="ft-header">
    <p class="ft-eyebrow">Utilities · markets</p>
    <h1 class="ft-title">FastToolbox</h1>
  </header>

  <div class="ft-tabs-wrap">
    <div
      class="ft-tabs"
      role="tablist"
      aria-label="FastToolbox sections"
    >
      {#each tabs as t (t.id)}
        <button
          type="button"
          class="ft-tab"
          class:ft-tab-active={activeTab === t.id}
          role="tab"
          aria-selected={activeTab === t.id}
          aria-controls="ft-panel-{t.id}"
          id="ft-tab-{t.id}"
          tabindex={activeTab === t.id ? 0 : -1}
          on:click={() => (activeTab = t.id)}
        >
          <span class="ft-tab-label">{t.label}</span>
          <span class="ft-tab-desc">{t.desc}</span>
        </button>
      {/each}
    </div>

    <div
      id="ft-panel-volume"
      class="ft-tab-panel"
      role="tabpanel"
      aria-labelledby="ft-tab-volume"
      hidden={activeTab !== "volume"}
    >
      <div class="ft-vol-host">
        <BinanceVolMonitor />
      </div>
    </div>

    <div
      id="ft-panel-radix"
      class="ft-tab-panel"
      role="tabpanel"
      aria-labelledby="ft-tab-radix"
      hidden={activeTab !== "radix"}
    >
      <section class="ft-panel ft-panel-single">
        <h2 class="ft-panel-title">Radix conversion</h2>
        <p class="ft-panel-desc">Decimal ↔ binary ↔ hexadecimal in one place.</p>
        <div class="ft-stack">
          <h3 class="ft-h3">Decimal to binary &amp; hex</h3>
          <label>
            Decimal
            <input bind:value={decimal1} on:input={handleDecimalInput} />
          </label>
          <label>
            Binary
            <input bind:value={binary1} />
          </label>
          <label>
            Hexadecimal
            <input bind:value={hex1} />
          </label>

          <h3 class="ft-h3">Hex to binary &amp; decimal</h3>
          <label>
            Hexadecimal
            <input bind:value={hex2} on:input={handleHexInput} />
          </label>
          <label>
            Binary
            <input bind:value={binary2} />
          </label>
          <label>
            Decimal
            <input bind:value={decimal2} />
          </label>
        </div>
      </section>
    </div>

    <div
      id="ft-panel-prices"
      class="ft-tab-panel"
      role="tabpanel"
      aria-labelledby="ft-tab-prices"
      hidden={activeTab !== "prices"}
    >
      <div class="ft-prices-grid">
        <section class="ft-panel ft-panel-accent">
          <h2 class="ft-panel-title">ARPA</h2>
          <p class="ft-panel-desc">Spot reference via CoinGecko proxy.</p>
          <div class="ft-stack">
            <h3 class="ft-h3">Current price</h3>
            <button type="button" on:click={() => getCurrentPrice("arpa")}
              >Fetch USD</button
            >
            <p class="ft-price">
              <span class="ft-price-label">Last</span>
              <span class="ft-price-value"
                >{arpaCurrentPrice === undefined ? "—" : arpaCurrentPrice}</span
              >
              <span class="ft-price-unit">USD</span>
            </p>

            <h3 class="ft-h3">Historical (date)</h3>
            <div class="ft-date-row">
              <DateInput bind:value={date1} />
            </div>
            <button
              type="button"
              on:click={() =>
                getHistoricalPrice("arpa", formatDate(date1, "dd-MM-yyyy"))}
              >Fetch for date</button
            >
            <p class="ft-price">
              <span class="ft-price-label">At date</span>
              <span class="ft-price-value"
                >{arpaHistoricalPrice === undefined
                  ? "—"
                  : arpaHistoricalPrice}</span
              >
              <span class="ft-price-unit">USD</span>
            </p>
          </div>
        </section>

        <section class="ft-panel">
          <h2 class="ft-panel-title">BEL</h2>
          <p class="ft-panel-desc">Bella Protocol — same proxy path.</p>
          <div class="ft-stack">
            <h3 class="ft-h3">Current price</h3>
            <button
              type="button"
              on:click={() => getCurrentPrice("bella-protocol")}>Fetch USD</button
            >
            <p class="ft-price">
              <span class="ft-price-label">Last</span>
              <span class="ft-price-value"
                >{belCurrentPrice === undefined ? "—" : belCurrentPrice}</span
              >
              <span class="ft-price-unit">USD</span>
            </p>

            <h3 class="ft-h3">Historical (date)</h3>
            <div class="ft-date-row">
              <DateInput bind:value={date2} />
            </div>
            <button
              type="button"
              on:click={() =>
                getHistoricalPrice(
                  "bella-protocol",
                  formatDate(date2, "dd-MM-yyyy")
                )}>Fetch for date</button
            >
            <p class="ft-price">
              <span class="ft-price-label">At date</span>
              <span class="ft-price-value"
                >{belHistoricalPrice === undefined ? "—" : belHistoricalPrice}</span
              >
              <span class="ft-price-unit">USD</span>
            </p>
          </div>
        </section>
      </div>
    </div>
  </div>
</div>

<style>
  .ft-app {
    max-width: 1180px;
    margin: 0 auto;
    padding: 0 1.25rem 4rem;
  }

  .ft-header {
    text-align: center;
    padding: 2.75rem 0.5rem 2rem;
    position: relative;
  }

  .ft-header::after {
    content: "";
    display: block;
    width: min(200px, 40%);
    height: 1px;
    margin: 1.75rem auto 0;
    background: linear-gradient(
      90deg,
      transparent,
      var(--ft-accent),
      transparent
    );
    opacity: 0.55;
  }

  .ft-eyebrow {
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.28em;
    text-transform: uppercase;
    color: var(--ft-accent);
    margin: 0 0 0.5rem;
  }

  .ft-title {
    font-family: var(--ft-font-display);
    font-size: clamp(2.5rem, 6vw, 3.75rem);
    font-weight: 600;
    letter-spacing: 0.02em;
    line-height: 1.05;
    margin: 0;
    color: var(--ft-text);
    text-shadow: 0 2px 40px rgba(0, 0, 0, 0.35);
  }

  .ft-tabs-wrap {
    margin-top: 0.25rem;
  }

  .ft-tabs {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    justify-content: center;
    margin-bottom: 1.35rem;
    padding: 0 0.25rem;
  }

  .ft-tab {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    text-align: left;
    gap: 0.2rem;
    min-width: min(100%, 11.5rem);
    padding: 0.65rem 1rem 0.7rem;
    margin: 0;
    border-radius: 12px;
    border: 1px solid var(--ft-line-strong);
    background: rgba(0, 0, 0, 0.28);
    color: var(--ft-text-soft);
    cursor: pointer;
    box-shadow: none;
    text-transform: none;
    letter-spacing: normal;
    font-size: inherit;
    transition:
      border-color 0.15s ease,
      background 0.15s ease,
      color 0.15s ease;
  }

  .ft-tab:hover {
    border-color: rgba(201, 169, 98, 0.35);
    color: var(--ft-text);
    background: rgba(0, 0, 0, 0.38);
  }

  .ft-tab-active {
    border-color: rgba(201, 169, 98, 0.55);
    background: rgba(201, 169, 98, 0.1);
    color: var(--ft-text);
    box-shadow: 0 0 0 1px rgba(201, 169, 98, 0.12);
  }

  .ft-tab-label {
    font-size: 0.78rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: inherit;
  }

  .ft-tab-desc {
    font-size: 0.68rem;
    font-weight: 400;
    color: var(--ft-muted);
    line-height: 1.35;
    letter-spacing: 0.02em;
  }

  .ft-tab-active .ft-tab-desc {
    color: var(--ft-text-soft);
  }

  .ft-tab-panel {
    outline: none;
  }

  .ft-vol-host :global(.bv-wrap) {
    margin-top: 0;
    margin-left: auto;
    margin-right: auto;
  }

  .ft-panel-single {
    max-width: 36rem;
    margin: 0 auto;
    width: 100%;
  }

  .ft-prices-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 1.25rem;
    align-items: stretch;
  }

  @media (min-width: 800px) {
    .ft-prices-grid {
      grid-template-columns: 1fr 1fr;
    }
  }

  .ft-panel {
    background: linear-gradient(
      160deg,
      rgba(28, 32, 41, 0.92) 0%,
      rgba(18, 20, 26, 0.96) 100%
    );
    border: 1px solid var(--ft-line);
    border-radius: var(--ft-radius);
    padding: 1.5rem 1.35rem 1.65rem;
    box-shadow: var(--ft-shadow);
    position: relative;
    overflow: hidden;
  }

  .ft-panel::before {
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
  }

  .ft-panel-accent {
    border-color: rgba(201, 169, 98, 0.12);
    box-shadow:
      var(--ft-shadow),
      0 0 40px -12px var(--ft-accent-glow);
  }

  .ft-panel-title {
    font-family: var(--ft-font-display);
    font-size: 1.55rem;
    font-weight: 600;
    margin: 0.35rem 0 0.35rem;
    letter-spacing: 0.03em;
    color: var(--ft-text);
  }

  .ft-panel-desc {
    margin: 0 0 1.25rem;
    font-size: 0.82rem;
    color: var(--ft-muted);
    line-height: 1.45;
  }

  .ft-stack {
    display: flex;
    flex-direction: column;
    gap: 0;
  }

  .ft-h3 {
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: var(--ft-text-soft);
    margin: 1.25rem 0 0.15rem;
    padding-top: 0.85rem;
    border-top: 1px solid var(--ft-line);
  }

  .ft-stack .ft-h3:first-of-type {
    margin-top: 0;
    padding-top: 0;
    border-top: none;
  }

  .ft-price {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.35rem 0.65rem;
    margin: 0.25rem 0 0.5rem;
    padding: 0.65rem 0.85rem;
    border-radius: var(--ft-radius-sm);
    background: rgba(0, 0, 0, 0.28);
    border: 1px solid var(--ft-line);
  }

  .ft-price-label {
    font-size: 0.65rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--ft-muted);
    width: 100%;
    margin-bottom: 0.15rem;
  }

  .ft-price-value {
    font-family: var(--ft-font-ui);
    font-size: 1.2rem;
    font-weight: 500;
    font-variant-numeric: tabular-nums;
    color: var(--ft-text);
    letter-spacing: 0.03em;
    font-feature-settings: "tnum" 1;
  }

  .ft-price-unit {
    font-size: 0.72rem;
    color: var(--ft-text-soft);
    font-weight: 500;
    letter-spacing: 0.06em;
  }

  .ft-date-row {
    --date-picker-background: rgba(22, 26, 32, 0.98);
    --date-picker-foreground: #e9e6e1;
    --date-picker-highlight-border: rgba(201, 169, 98, 0.8);
    --date-picker-highlight-shadow: rgba(201, 169, 98, 0.32);
    --date-picker-selected-background: rgba(201, 169, 98, 0.2);
    --date-picker-selected-color: #fdfbf7;
    --date-picker-today-border: rgba(201, 169, 98, 0.55);
    --date-input-width: 100%;
    position: relative;
    z-index: 2;
    margin-bottom: 0.35rem;
  }

  .ft-date-row :global(.date-time-field) {
    width: 100%;
    max-width: 100%;
  }

  .ft-date-row :global(.date-time-field > input) {
    width: 100%;
    max-width: 100%;
    box-sizing: border-box;
    padding: 0.55rem 0.75rem;
    margin: 0 0 0.35rem 0;
    border-radius: var(--ft-radius-sm);
    border: 1px solid var(--ft-line-strong);
    background: rgba(0, 0, 0, 0.28);
    color: var(--ft-text);
    font-family: var(--ft-font-ui);
    font-size: 0.88rem;
    font-variant-numeric: tabular-nums;
    transition:
      border-color 0.15s ease,
      box-shadow 0.15s ease;
  }

  .ft-date-row :global(.date-time-field > input:focus) {
    border-color: rgba(201, 169, 98, 0.55);
    box-shadow: 0 0 0 3px rgba(201, 169, 98, 0.22);
  }

  .ft-date-row :global(.date-time-field > input.invalid) {
    border-color: rgba(248, 113, 113, 0.55);
    background: rgba(127, 29, 29, 0.2);
  }

  .ft-date-row :global(.picker.visible) {
    z-index: 80;
    margin-top: 4px;
  }

  .ft-date-row :global(.date-time-picker) {
    border-radius: var(--ft-radius-sm);
    border: 1px solid var(--ft-line-strong);
    box-shadow: 0 18px 48px rgba(0, 0, 0, 0.55);
    font-family: var(--ft-font-ui);
    font-size: 0.78rem;
    padding: 0.55rem 0.5rem 0.6rem;
  }

  .ft-date-row :global(.date-time-picker:focus) {
    border-color: rgba(201, 169, 98, 0.45);
    box-shadow:
      0 0 0 2px rgba(201, 169, 98, 0.2),
      0 18px 48px rgba(0, 0, 0, 0.55);
  }

  .ft-date-row :global(.date-time-picker .header) {
    color: var(--ft-muted);
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    font-size: 0.62rem;
    padding-bottom: 0.35rem;
  }

  .ft-date-row :global(.date-time-picker .header-cell) {
    width: 2rem;
    opacity: 0.9;
  }

  .ft-date-row :global(.date-time-picker button.page-button) {
    width: 1.65rem;
    height: 1.65rem;
    padding: 0;
    margin: 0;
    border-radius: 8px;
    border: 1px solid transparent;
    background: transparent;
    box-shadow: none;
    text-transform: none;
    letter-spacing: normal;
    font-size: inherit;
    min-width: 0;
  }

  .ft-date-row :global(.date-time-picker button.page-button:hover) {
    background: rgba(255, 255, 255, 0.07);
    border-color: rgba(255, 255, 255, 0.1);
  }

  .ft-date-row :global(.date-time-picker select.dummy-select) {
    color: var(--ft-text);
    background: rgba(0, 0, 0, 0.35);
    border: 1px solid var(--ft-line-strong);
    border-radius: 8px;
    height: 1.65rem;
    font-size: 0.72rem;
    font-weight: 500;
  }

  .ft-date-row :global(.date-time-picker select:not(.dummy-select)) {
    border-radius: 8px;
    border: 1px solid var(--ft-line-strong);
  }

  .ft-date-row :global(.date-time-picker .cell) {
    border-radius: 8px;
    font-variant-numeric: tabular-nums;
    font-weight: 500;
  }

  .ft-date-row :global(.date-time-picker .cell:hover) {
    background: rgba(255, 255, 255, 0.06);
    border-color: rgba(255, 255, 255, 0.08);
  }

  .ft-date-row :global(.date-time-picker .cell.other-month span) {
    opacity: 0.28;
  }

  .ft-date-row :global(.time-picker) {
    border: 1px solid var(--ft-line-strong);
    border-radius: 8px;
    background: rgba(0, 0, 0, 0.28);
    color: var(--ft-text);
    margin-top: 0.5rem;
    padding: 0.15rem 0.25rem;
  }

  .ft-date-row :global(.time-picker span:focus) {
    outline: 1px solid rgba(201, 169, 98, 0.45);
    outline-offset: 1px;
    border-radius: 4px;
  }
</style>
