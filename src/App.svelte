<script lang="ts">
  import { decToBin, decToHex, hexToBin, hexToDec } from "./converter.js";
  import { DateInput } from "date-picker-svelte";

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

  function getCurrentPrice(token) {
    fetch(
      `https://api.coingecko.com/api/v3/simple/price?ids=${token}&vs_currencies=usd`
    )
      .then((response) => response.json())
      .then((data) => {
        if (token === "bella-protocol")
          belCurrentPrice = data["bella-protocol"].usd;
        else arpaCurrentPrice = data.arpa.usd;
      });
  }

  function getHistoricalPrice(token, date) {
    fetch(
      `https://api.coingecko.com/api/v3/coins/${token}/history?date=${date}`
    )
      .then((response) => response.json())
      .then((data) => {
        if (token === "bella-protocol")
          belHistoricalPrice = data.market_data.current_price.usd;
        else arpaHistoricalPrice = data.market_data.current_price.usd;
      });
  }
</script>

<svelte:head>
  <title>FastToolbox</title>
  <meta name="robots" content="noindex nofollow" />
  <html lang="en" />
</svelte:head>

<h1>FastToolbox</h1>
<main>
  <div>
    <h2>Decimal to Binary and Hexadecimal</h2>
    <label>
      decimal:
      <input bind:value={decimal1} on:input={handleDecimalInput} />
    </label>
    <label>
      binary:
      <input bind:value={binary1} />
    </label>
    <label>
      hexadecimal:
      <input bind:value={hex1} />
    </label>

    <h2>Hexadecimal to Binary and Decimal</h2>
    <label>
      hexadecimal:
      <input bind:value={hex2} on:input={handleHexInput} />
    </label>
    <label>
      binary:
      <input bind:value={binary2} />
    </label>
    <label>
      decimal:
      <input bind:value={decimal2} />
    </label>
  </div>

  <!-- arpa -->
  <div>
    <h2>Get current price of ARPA</h2>
    <button on:click={() => getCurrentPrice("arpa")}>Query</button>
    price: {arpaCurrentPrice === undefined ? "..." : arpaCurrentPrice} USD

    <h2>Get historical price of ARPA</h2>
    <DateInput bind:value={date1} />
    <button
      on:click={() =>
        getHistoricalPrice("arpa", formatDate(date1, "dd-MM-yyyy"))}
      >Query</button
    >
    price: {arpaHistoricalPrice === undefined ? "..." : arpaHistoricalPrice} USD
  </div>
  <!-- bel -->
  <div>
    <h2>Get current price of BEL</h2>
    <button on:click={() => getCurrentPrice("bella-protocol")}>Query</button>
    price: {belCurrentPrice === undefined ? "..." : belCurrentPrice} USD

    <h2>Get historical price of BEL</h2>
    <DateInput bind:value={date2} />
    <button
      on:click={() =>
        getHistoricalPrice("bella-protocol", formatDate(date2, "dd-MM-yyyy"))}
      >Query</button
    >
    price: {belHistoricalPrice === undefined ? "..." : belHistoricalPrice} USD
  </div>
</main>

<style>
  h1 {
    text-align: center;
    margin-bottom: 2em;
  }
  main {
    display: flex;
    width: 80%;
    justify-content: space-between;
    margin: 0 auto;
  }
  @media (min-width: 640px) {
    main {
      max-width: none;
    }
  }
</style>
