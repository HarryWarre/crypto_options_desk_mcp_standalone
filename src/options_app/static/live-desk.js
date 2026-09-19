(() => {
  "use strict";

  const EMPTY_MARKET_MESSAGE = "Chọn tài sản trong bộ lọc scanner để xem ticker live.";

  function firstDefined(...values) {
    return values.find((value) => value !== null && value !== undefined && value !== "");
  }

  function record(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : null;
  }

  function finiteNumber(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function countValue(value) {
    if (Array.isArray(value)) return value.length;
    const direct = finiteNumber(value);
    if (direct !== null) return direct;
    const object = record(value);
    if (!object) return null;
    const nested = firstDefined(
      object.count,
      object.total,
      object.contract_count,
      object.contracts_count,
      object.option_count,
      object.value,
    );
    return nested === undefined ? null : finiteNumber(nested);
  }

  function sumCountMap(value) {
    if (Array.isArray(value)) return value.reduce((sum) => sum + 1, 0);
    const object = record(value);
    if (!object) return null;
    const values = Object.values(object).map(countValue).filter((item) => item !== null);
    return values.length ? values.reduce((sum, item) => sum + item, 0) : null;
  }

  function readCount(object, keys) {
    for (const key of keys) {
      if (!Object.prototype.hasOwnProperty.call(object, key)) continue;
      const value = countValue(object[key]);
      if (value !== null) return value;
      const mapped = sumCountMap(object[key]);
      if (mapped !== null) return mapped;
    }
    return null;
  }

  function spotValue(value) {
    const direct = finiteNumber(value);
    if (direct !== null) return direct;
    const object = record(value);
    if (!object) return null;
    return finiteNumber(firstDefined(
      object.price,
      object.value,
      object.spot_price,
      object.underlying_price,
      object.last_price,
      object.last,
    ));
  }

  function compactNumber(value) {
    const amount = finiteNumber(value);
    if (amount === null) return "—";
    if (Math.abs(amount) >= 1_000_000) return `${(amount / 1_000_000).toFixed(1)}m`;
    if (Math.abs(amount) >= 1_000) return `${(amount / 1_000).toFixed(1)}k`;
    return amount.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }

  function countLabel(value) {
    const count = finiteNumber(value);
    return count === null ? "—" : Math.round(count).toLocaleString("en-US");
  }

  function normalizeOptionQuote(value) {
    const object = record(value) || {};
    const symbol = String(firstDefined(object.symbol, object.instrument, object.option_symbol, "")).trim();
    if (!symbol) return null;
    const asset = cardAsset(value, "—");
    return {
      asset,
      symbol,
      optionType: firstDefined(object.option_type, object.optionType, object.type, "—"),
      strike: finiteNumber(object.strike),
      expiryAt: firstDefined(object.expiry_at, object.expiryAt, object.expiry),
      spot: spotValue(firstDefined(object.spot_price, object.spot, object.underlying_price)),
      bid: finiteNumber(firstDefined(object.bid_price, object.bid)),
      ask: finiteNumber(firstDefined(object.ask_price, object.ask)),
      mark: finiteNumber(firstDefined(object.mark_price, object.mark, object.market_mid)),
      iv: finiteNumber(firstDefined(object.mark_iv, object.iv, object.market_iv)),
      delta: finiteNumber(object.delta),
      volume: finiteNumber(firstDefined(object.volume_24h, object.volume)),
      openInterest: finiteNumber(firstDefined(object.open_interest, object.oi)),
      quoteTimestamp: firstDefined(object.quote_timestamp, object.quoteTimestamp, object.timestamp, object.updated_at),
    };
  }

  function uniqueStrings(values) {
    return [...new Set(values.map((value) => String(value || "").trim()).filter(Boolean))];
  }

  function recordsFrom(value) {
    if (Array.isArray(value)) return value;
    const object = record(value);
    if (!object) return [];
    const nested = firstDefined(object.market_cards, object.cards, object.markets, object.items, object.data);
    if (Array.isArray(nested)) return nested;
    return Object.entries(object).map(([asset, details]) => ({
      ...(record(details) || {}),
      asset: firstDefined(record(details)?.asset, record(details)?.base_coin, asset),
      ...(record(details) ? {} : { spot_price: details }),
    }));
  }

  function cardAsset(value, fallback) {
    const object = record(value);
    return String(firstDefined(
      object?.asset,
      object?.base_coin,
      object?.underlying,
      object?.underlying_asset,
      object?.name,
      fallback,
      "—",
    ));
  }

  function normalizeMarketCard(value, fallbackAsset, optionItems) {
    const object = record(value) || {};
    const asset = cardAsset(value, fallbackAsset);
    const spot = spotValue(firstDefined(
      object.spot_price,
      object.spot,
      object.underlying_price,
      object.price,
      object.quote,
      value,
    ));
    const contractCount = readCount(object, [
      "contract_count",
      "contracts_count",
      "option_contract_count",
      "options_count",
      "contracts",
    ]);
    const validQuoteCount = readCount(object, ["valid_quote_count", "valid_quotes", "quoted_contract_count"]);
    const quoteTimestamp = firstDefined(
      object.quote_timestamp,
      object.data_timestamp,
      object.timestamp,
      object.updated_at,
    );
    const quoteSource = firstDefined(object.quote_source, object.source, object.status);
    return {
      asset,
      spot,
      contractCount,
      validQuoteCount,
      quoteCount: optionItems.length,
      quoteTimestamp,
      quoteSource,
    };
  }

  function spotFromDesk(raw, markets, opportunities, selectedAssets) {
    const sources = [raw, record(raw.summary) || {}];
    for (const source of sources) {
      const directSpot = firstDefined(
        source.spot_price,
        source.underlying_price,
        source.spot,
        source.price,
      );
      const directValue = spotValue(directSpot);
      if (directValue !== null) {
        return {
          value: directValue,
          asset: String(firstDefined(source.asset, source.base_coin, selectedAssets[0], "Underlying")),
          source: firstDefined(source.quote_source, source.source),
          timestamp: firstDefined(source.quote_timestamp, source.data_timestamp, source.timestamp),
        };
      }

      const mappedSpot = firstDefined(source.spot_prices, source.spots, source.underlyings);
      const mapped = record(mappedSpot);
      if (mapped) {
        const preferredAsset = uniqueStrings([
          ...selectedAssets,
          ...markets.map((market) => market.asset),
          ...opportunities.map((item) => item.asset),
        ]).find((asset) => Object.prototype.hasOwnProperty.call(mapped, asset));
        const key = preferredAsset || Object.keys(mapped)[0];
        const value = spotValue(mapped[key]);
        if (value !== null) {
          const detail = record(mapped[key]);
          return {
            value,
            asset: key || "Underlying",
            source: firstDefined(detail?.quote_source, detail?.source, source.quote_source, source.source),
            timestamp: firstDefined(detail?.quote_timestamp, detail?.timestamp, source.timestamp),
          };
        }
      }
    }

    const market = markets.find((item) => item.spot !== null);
    if (market) return {
      value: market.spot,
      asset: market.asset,
      source: market.quoteSource,
      timestamp: market.quoteTimestamp,
    };
    const opportunity = opportunities.find((item) => spotValue(item.spot_price) !== null);
    return opportunity
      ? {
        value: spotValue(opportunity.spot_price),
        asset: firstDefined(opportunity.asset, "Underlying"),
        source: opportunity.quote_timestamp ? "quote" : "model",
        timestamp: opportunity.quote_timestamp,
      }
      : null;
  }

  function addReason(reasons, reason, count) {
    const label = String(firstDefined(reason, "unknown_rejection"));
    const amount = finiteNumber(count) ?? 1;
    reasons.set(label, (reasons.get(label) || 0) + amount);
  }

  function readReasonRows(source, reasons) {
    if (Array.isArray(source)) {
      source.forEach((item) => {
        const object = record(item) || {};
        const reasonList = Array.isArray(object.reasons) ? object.reasons : null;
        if (reasonList?.length) reasonList.forEach((reason) => addReason(reasons, reason, object.count));
        else addReason(reasons, firstDefined(object.reason, object.code, object.category, object.message, item), object.count);
      });
      return;
    }
    const object = record(source);
    if (!object) return;
    Object.entries(object).forEach(([reason, count]) => {
      if (["total", "count", "rejected", "rejection_count", "items"].includes(reason)) return;
      const amount = countValue(count);
      if (amount !== null) addReason(reasons, reason, amount);
    });
  }

  function rejectionSummary(payload, raw) {
    const reasons = new Map();
    const source = firstDefined(
      raw.rejection_summary,
      raw.rejections_summary,
      raw.rejected_summary,
      raw.rejections,
      raw.rejection_reasons,
      payload.rejection_summary,
    );
    let total = null;
    if (Array.isArray(source)) {
      total = source.length;
      readReasonRows(source, reasons);
    } else if (record(source)) {
      total = finiteNumber(firstDefined(
        source.total,
        source.count,
        source.rejected,
        source.rejection_count,
      ));
      const rows = firstDefined(source.reasons, source.by_reason, source.reason_counts, source.breakdown, source.items);
      readReasonRows(rows === undefined ? source : rows, reasons);
    }

    const fallbackRejections = Array.isArray(payload.rejections) ? payload.rejections : [];
    if (source === undefined && fallbackRejections.length) {
      total = fallbackRejections.length;
      readReasonRows(fallbackRejections, reasons);
    }
    if (total === null && reasons.size) total = [...reasons.values()].reduce((sum, count) => sum + count, 0);
    return {
      total,
      reasons: [...reasons.entries()]
        .map(([reason, count]) => ({ reason, count }))
        .sort((left, right) => right.count - left.count),
    };
  }

  function normalizeSnapshot(payload, getSelectedAssets) {
    const safePayload = record(payload) || {};
    const raw = record(safePayload.live_desk) || {};
    const opportunities = Array.isArray(safePayload.opportunities) ? safePayload.opportunities : [];
    const selectedAssets = uniqueStrings(getSelectedAssets?.() || []);
    const rawCards = firstDefined(
      raw.market_cards,
      raw.marketCards,
      raw.markets,
      raw.cards,
      raw.assets,
      raw.observed_assets,
    );
    const rawOptionQuotes = firstDefined(
      raw.option_quotes,
      raw.optionQuotes,
      raw.options,
      raw.quotes,
    );
    const cardRecords = recordsFrom(rawCards);
    const cardAssets = cardRecords.map((item) => cardAsset(item));
    const optionQuotes = recordsFrom(rawOptionQuotes)
      .map(normalizeOptionQuote)
      .filter(Boolean);
    const assets = uniqueStrings([
      ...selectedAssets,
      ...cardAssets,
      ...optionQuotes.map((quote) => quote.asset),
    ]);
    const markets = assets.map((asset) => {
      const card = cardRecords.find((item) => cardAsset(item) === asset);
      return normalizeMarketCard(card || { asset }, asset, optionQuotes.filter((quote) => quote.asset === asset));
    });
    const summary = record(raw.summary) || {};
    const contractCount = firstDefined(
      readCount(raw, ["contract_count", "contracts_count", "total_contracts", "option_contract_count", "contracts"]),
      readCount(summary, ["contract_count", "contracts_count", "total_contracts", "contracts"]),
      markets.reduce((sum, market) => sum + (market.contractCount || 0), 0) || null,
    );
    return {
      opportunities,
      optionQuotes,
      markets,
      spot: spotFromDesk(raw, markets, opportunities, selectedAssets),
      contractCount,
      rejectionSummary: rejectionSummary(safePayload, raw),
    };
  }

  function appendCell(row, value, className = "") {
    const cell = document.createElement("td");
    cell.textContent = value;
    if (className) cell.className = className;
    row.appendChild(cell);
  }

  function createController(options = {}) {
    const elements = options.elements || {};
    const getSelectedAssets = options.getSelectedAssets || (() => []);
    const onLog = options.onLog || (() => {});
    const serviceStatus = elements.serviceStatus;
    let socket = null;
    let reconnectTimer = null;
    let request = null;
    let wanted = false;
    let updateCount = 0;
    let state = "idle";
    let selectedOptionSymbol = null;
    let latestOptionQuotes = [];
    const optionHistory = new Map();

    if (elements.liveOptionSelect) {
      elements.liveOptionSelect.addEventListener("change", () => {
        selectedOptionSymbol = elements.liveOptionSelect.value || null;
        renderOptionChart(latestOptionQuotes, selectedOptionSymbol, optionHistory);
      });
    }

    function setServiceStatus(message, isError = false) {
      if (!serviceStatus) return;
      serviceStatus.textContent = message;
      serviceStatus.classList.toggle("error", isError);
    }

    function setConnectionState(nextState, label) {
      state = nextState;
      const { liveConnection, liveConnectionLabel, liveSessionState, liveToggle } = elements;
      if (liveConnection) liveConnection.className = `live-connection live-connection-${nextState}`;
      if (liveConnectionLabel) liveConnectionLabel.textContent = label;
      if (liveSessionState) {
        liveSessionState.textContent = nextState === "live"
          ? "LIVE"
          : nextState === "connecting"
            ? "SYNC"
            : nextState === "stale"
              ? "STALE"
              : "WAITING";
      }
      if (liveToggle) {
        liveToggle.textContent = nextState === "live" || nextState === "connecting"
          ? "Dừng live feed"
          : nextState === "stale"
            ? "Kết nối lại"
            : "Bật live feed";
      }
    }

    function renderMarketStrip(model) {
      const target = elements.marketStrip;
      if (!target) return;
      target.replaceChildren();
      if (!model.markets.length) {
        const empty = document.createElement("div");
        empty.className = "market-strip-empty";
        empty.textContent = EMPTY_MARKET_MESSAGE;
        target.appendChild(empty);
        return;
      }
      model.markets.forEach((market) => {
        const card = document.createElement("div");
        card.className = "market-card";
        const heading = document.createElement("div");
        heading.className = "market-card-heading";
        const name = document.createElement("strong");
        name.textContent = market.asset;
        const dot = document.createElement("span");
        dot.className = market.spot !== null ? "market-card-dot" : "market-card-dot market-card-dot-muted";
        dot.setAttribute("aria-hidden", "true");
        heading.append(name, dot);
        const spot = document.createElement("strong");
        spot.className = "market-card-price";
        spot.textContent = compactNumber(market.spot);
        const detail = document.createElement("span");
        detail.className = "market-card-detail";
        const detailParts = [];
        if (market.contractCount !== null) {
          const contractText = `${countLabel(market.contractCount)} contracts`;
          detailParts.push(market.validQuoteCount === null
            ? contractText
            : `${contractText} · ${countLabel(market.validQuoteCount)} valid quotes`);
        }
        detailParts.push(`${countLabel(market.quoteCount)} option quote${market.quoteCount === 1 ? "" : "s"}`);
        detail.textContent = detailParts.join(" · ") || "Chưa có market data";
        card.append(heading, spot, detail);
        target.appendChild(card);
      });
    }

    function renderOptionSelector(quotes, selectedSymbol) {
      const target = elements.liveOptionSelect;
      if (!target) return selectedSymbol;
      target.replaceChildren();
      if (!quotes.length) {
        const empty = document.createElement("option");
        empty.textContent = "Chưa có option quote";
        empty.value = "";
        target.appendChild(empty);
        return null;
      }
      quotes.forEach((quote) => {
        const option = document.createElement("option");
        option.value = quote.symbol;
        option.textContent = `${quote.asset} · ${quote.symbol}`;
        target.appendChild(option);
      });
      const nextSymbol = quotes.some((quote) => quote.symbol === selectedSymbol)
        ? selectedSymbol
        : quotes[0].symbol;
      target.value = nextSymbol;
      return nextSymbol;
    }

    function renderOptionTape(quotes) {
      const target = elements.liveOptionTape;
      if (!target) return;
      target.replaceChildren();
      if (!quotes.length) {
        const row = document.createElement("tr");
        const empty = document.createElement("td");
        empty.colSpan = 6;
        empty.className = "live-board-empty";
        empty.textContent = "Chưa có option quote từ WebSocket.";
        row.appendChild(empty);
        target.appendChild(row);
        return;
      }
      quotes.slice(0, 12).forEach((quote) => {
        const row = document.createElement("tr");
        const instrument = document.createElement("td");
        instrument.className = "live-board-instrument";
        const asset = document.createElement("strong");
        asset.textContent = quote.asset;
        const symbol = document.createElement("span");
        symbol.textContent = quote.symbol;
        instrument.append(asset, symbol);
        row.appendChild(instrument);
        appendCell(row, compactNumber(quote.bid));
        appendCell(row, compactNumber(quote.ask));
        appendCell(row, compactNumber(quote.mark));
        appendCell(row, quote.iv === null ? "—" : `${(quote.iv * 100).toFixed(2)}%`);
        appendCell(row, quote.quoteTimestamp ? new Date(quote.quoteTimestamp).toLocaleTimeString("vi-VN") : "—");
        target.appendChild(row);
      });
    }

    function svgNode(name, attributes = {}) {
      const node = document.createElementNS("http://www.w3.org/2000/svg", name);
      Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
      return node;
    }

    function renderOptionChart(quotes, selectedSymbol, history) {
      const target = elements.liveOptionChart || elements.signalChart;
      if (!target) return;
      target.replaceChildren();
      const quote = quotes.find((item) => item.symbol === selectedSymbol) || quotes[0];
      if (!quote) {
        const empty = document.createElement("div");
        empty.className = "signal-chart-empty";
        empty.textContent = "Option quotes live sẽ xuất hiện ở đây.";
        target.appendChild(empty);
        if (elements.liveSignalStatus) elements.liveSignalStatus.textContent = "Đang chờ option quote";
        return;
      }
      const caption = document.createElement("div");
      caption.className = "live-option-chart-caption";
      const symbol = document.createElement("strong");
      symbol.textContent = quote.symbol;
      const quoteMeta = document.createElement("span");
      quoteMeta.textContent = `Bid ${compactNumber(quote.bid)} · Ask ${compactNumber(quote.ask)} · Mark ${compactNumber(quote.mark)} · IV ${quote.iv === null ? "—" : `${(quote.iv * 100).toFixed(2)}%`}`;
      caption.append(symbol, quoteMeta);
      target.appendChild(caption);

      const points = history.get(quote.symbol) || [];
      const values = points.flatMap((point) => [point.bid, point.ask, point.mark]).filter((value) => value !== null);
      if (!values.length) return;
      const width = 760;
      const height = 230;
      const padding = { top: 18, right: 20, bottom: 28, left: 44 };
      const minValue = Math.min(...values);
      const maxValue = Math.max(...values);
      const range = Math.max(maxValue - minValue, Math.max(Math.abs(maxValue), 1) * 0.01);
      const lower = minValue - range * 0.12;
      const upper = maxValue + range * 0.12;
      const plotWidth = width - padding.left - padding.right;
      const plotHeight = height - padding.top - padding.bottom;
      const xFor = (index) => padding.left + (points.length <= 1 ? plotWidth / 2 : index / (points.length - 1) * plotWidth);
      const yFor = (value) => padding.top + (upper - value) / (upper - lower) * plotHeight;
      const chart = svgNode("svg", { class: "option-quote-svg", viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": `Giá bid ask mark realtime của ${quote.symbol}` });
      [0, 0.5, 1].forEach((ratio) => {
        const y = padding.top + ratio * plotHeight;
        chart.appendChild(svgNode("line", { x1: padding.left, x2: width - padding.right, y1: y, y2: y, class: "option-chart-grid" }));
        const label = svgNode("text", { x: padding.left - 8, y: y + 4, class: "option-chart-axis-label", "text-anchor": "end" });
        label.textContent = compactNumber(upper - ratio * (upper - lower));
        chart.appendChild(label);
      });
      const pathFor = (key, className, pointClass) => {
        const pathPoints = points.map((point, index) => point[key] === null ? null : `${xFor(index)},${yFor(point[key])}`).filter(Boolean);
        if (!pathPoints.length) return;
        chart.appendChild(svgNode("path", { d: `M ${pathPoints.join(" L ")}`, class: className }));
        points.forEach((point, index) => {
          if (point[key] === null) return;
          chart.appendChild(svgNode("circle", {
            cx: xFor(index),
            cy: yFor(point[key]),
            r: 3.5,
            class: pointClass,
          }));
        });
      };
      pathFor("bid", "option-chart-line option-chart-line-bid", "option-chart-point option-chart-point-bid");
      pathFor("ask", "option-chart-line option-chart-line-ask", "option-chart-point option-chart-point-ask");
      pathFor("mark", "option-chart-line option-chart-line-mark", "option-chart-point option-chart-point-mark");
      target.appendChild(chart);
      const legend = document.createElement("div");
      legend.className = "live-option-chart-legend";
      legend.textContent = `BID / ASK / MARK · ${points.length} snapshots · dữ liệu trực tiếp từ WebSocket`;
      target.appendChild(legend);
      if (elements.liveSignalStatus) elements.liveSignalStatus.textContent = `${points.length} snapshot · ${quote.symbol}`;
    }

    function rememberOptionQuotes(quotes, timestamp) {
      quotes.forEach((quote) => {
        const points = optionHistory.get(quote.symbol) || [];
        points.push({
          timestamp: firstDefined(quote.quoteTimestamp, timestamp),
          bid: quote.bid,
          ask: quote.ask,
          mark: quote.mark,
        });
        optionHistory.set(quote.symbol, points.slice(-32));
      });
    }

    function renderFeed(optionQuotes) {
      const target = elements.liveFeed;
      if (!target) return;
      target.replaceChildren();
      if (!optionQuotes.length) {
        const empty = document.createElement("div");
        empty.className = "live-feed-empty";
        empty.textContent = "Snapshot đã nhận nhưng chưa có option quote.";
        target.appendChild(empty);
        return;
      }
      optionQuotes.slice(0, 6).forEach((quote, index) => {
        const event = document.createElement("div");
        event.className = "live-event";
        const indexLabel = document.createElement("span");
        indexLabel.className = "live-event-index";
        indexLabel.textContent = String(index + 1).padStart(2, "0");
        const copy = document.createElement("div");
        copy.className = "live-event-copy";
        const title = document.createElement("strong");
        title.textContent = `${quote.asset} · Option quote`;
        const symbol = document.createElement("span");
        symbol.textContent = `${quote.symbol} · Bid ${compactNumber(quote.bid)} · Ask ${compactNumber(quote.ask)}`;
        copy.append(title, symbol);
        const edge = document.createElement("strong");
        edge.className = "live-event-edge positive";
        edge.textContent = compactNumber(quote.mark);
        event.append(indexLabel, copy, edge);
        target.appendChild(event);
      });
    }

    function renderRejectionSummary(summary) {
      const target = elements.liveRejectionSummary;
      if (!target) return;
      target.replaceChildren();
      const title = document.createElement("span");
      title.className = "live-rejection-title";
      title.textContent = "REJECTION SUMMARY";
      target.appendChild(title);
      const total = document.createElement("strong");
      total.textContent = summary.total === null ? "Chưa có dữ liệu rejection" : `${countLabel(summary.total)} rejection${summary.total === 1 ? "" : "s"}`;
      target.appendChild(total);
      if (summary.reasons.length) {
        const list = document.createElement("ul");
        summary.reasons.slice(0, 5).forEach((item) => {
          const row = document.createElement("li");
          const reason = document.createElement("span");
          reason.textContent = item.reason;
          const count = document.createElement("b");
          count.textContent = countLabel(item.count);
          row.append(reason, count);
          list.appendChild(row);
        });
        target.appendChild(list);
      }
    }

    function renderLiveSnapshot(payload) {
      const model = normalizeSnapshot(payload, getSelectedAssets);
      const opportunities = model.opportunities;
      latestOptionQuotes = model.optionQuotes;
      rememberOptionQuotes(latestOptionQuotes, firstDefined(payload?.data_timestamp, payload?.timestamp, Date.now()));
      selectedOptionSymbol = renderOptionSelector(latestOptionQuotes, selectedOptionSymbol);
      const first = opportunities[0];
      const selectedQuote = latestOptionQuotes.find((quote) => quote.symbol === selectedOptionSymbol) || latestOptionQuotes[0];
      updateCount += 1;
      if (elements.liveUpdateCountLabel) elements.liveUpdateCountLabel.textContent = `${updateCount} cập nhật`;
      if (elements.liveLastUpdate) {
        const timestamp = firstDefined(payload?.data_timestamp, payload?.timestamp, Date.now());
        elements.liveLastUpdate.textContent = `Cập nhật ${new Date(timestamp).toLocaleTimeString("vi-VN")}`;
      }
      if (elements.liveNextRefresh) elements.liveNextRefresh.textContent = "Snapshot mới mỗi 8 giây · quote server-side";
      if (elements.liveStatSpot) elements.liveStatSpot.textContent = compactNumber(model.spot?.value ?? first?.spot_price);
      if (elements.liveStatSpotLabel) {
        const spotAsset = firstDefined(model.spot?.asset, first?.asset, "Underlying");
        const source = model.spot?.source || (first?.quote_timestamp ? "quote nhận được" : "quote model");
        elements.liveStatSpotLabel.textContent = model.spot || first ? `${spotAsset} · ${source}` : "Chưa có quote phù hợp";
      }
      if (elements.liveStatOpportunities) elements.liveStatOpportunities.textContent = countLabel(latestOptionQuotes.length);
      if (elements.liveStatOpportunitiesLabel) elements.liveStatOpportunitiesLabel.textContent = latestOptionQuotes.length ? "Option quotes từ WebSocket" : "Chưa có option quote";
      if (elements.liveStatEdge) elements.liveStatEdge.textContent = compactNumber(selectedQuote?.mark);
      if (elements.liveStatDte) elements.liveStatDte.textContent = selectedQuote
        ? `Bid ${compactNumber(selectedQuote.bid)} · Ask ${compactNumber(selectedQuote.ask)}`
        : "Chưa chọn mã";
      if (elements.liveStatContracts) elements.liveStatContracts.textContent = countLabel(model.contractCount);
      if (elements.liveStatContractsLabel) elements.liveStatContractsLabel.textContent = model.markets.length
        ? `${model.markets.length} market${model.markets.length > 1 ? "s" : ""} trong snapshot`
        : "Chưa có contract inventory";
      if (elements.liveStatRejections) elements.liveStatRejections.textContent = countLabel(model.rejectionSummary.total);
      if (elements.liveStatRejectionsLabel) elements.liveStatRejectionsLabel.textContent = model.rejectionSummary.reasons.length
        ? `${model.rejectionSummary.reasons[0].reason}`
        : "Không có rejection summary";
      renderMarketStrip(model);
      renderOptionChart(latestOptionQuotes, selectedOptionSymbol, optionHistory);
      renderOptionTape(latestOptionQuotes);
      renderFeed(latestOptionQuotes);
      renderRejectionSummary(model.rejectionSummary);
      setConnectionState("live", `Live feed · ${latestOptionQuotes.length} option quotes`);
      setServiceStatus("Live stream đang hoạt động");
    }

    function scheduleReconnect() {
      if (!wanted || reconnectTimer) return;
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        if (wanted && request) connectLiveFeed(request, true);
      }, 1800);
      if (elements.liveNextRefresh) elements.liveNextRefresh.textContent = "Đang thử kết nối lại…";
    }

    function connectLiveFeed(nextRequest, isReconnect = false) {
      if (reconnectTimer) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      if (socket) {
        const previousSocket = socket;
        socket = null;
        previousSocket.close();
      }
      wanted = true;
      request = nextRequest;
      updateCount = isReconnect ? updateCount : 0;
      setConnectionState("connecting", isReconnect ? "Đang reconnect live feed…" : "Đang kết nối live feed…");
      const protocol = window.location.protocol === "https:" ? "wss" : "ws";
      const currentSocket = new WebSocket(`${protocol}://${window.location.host}/api/v1/opportunities/stream`);
      socket = currentSocket;
      currentSocket.addEventListener("open", () => {
        currentSocket.send(JSON.stringify(nextRequest));
        if (elements.liveNextRefresh) elements.liveNextRefresh.textContent = "Đã mở kênh · chờ snapshot đầu tiên";
      });
      currentSocket.addEventListener("message", (event) => {
        let envelope;
        try {
          envelope = JSON.parse(event.data);
        } catch (_error) {
          onLog("[LIVE] Nhận event không hợp lệ.", "error");
          return;
        }
        if (envelope.type === "snapshot") {
          renderLiveSnapshot(envelope.payload || {});
          return;
        }
        if (envelope.type === "log") {
          onLog(`[LIVE] ${envelope.message || "Đang cập nhật…"}`);
          return;
        }
        if (envelope.type === "error") {
          setConnectionState("error", envelope.message || "Live feed gặp lỗi");
          setServiceStatus("Live stream gặp lỗi", true);
          onLog(`[LIVE] LỖI: ${envelope.message || "Live feed gặp lỗi"}`, "error");
          return;
        }
        if (envelope.status === "starting") setConnectionState("connecting", "Đang dựng snapshot live…");
        if (envelope.status === "connected" && socket === currentSocket && updateCount === 0) {
          setConnectionState("connecting", "Đã kết nối · đang chờ dữ liệu");
        }
      });
      currentSocket.addEventListener("error", () => {
        if (socket !== currentSocket) return;
        setConnectionState("stale", "Không kết nối được · đang thử lại");
        setServiceStatus("Live stream không sẵn sàng", true);
      });
      currentSocket.addEventListener("close", () => {
        if (socket !== currentSocket) return;
        socket = null;
        if (wanted) {
          setConnectionState("stale", "Stream bị ngắt · đang thử lại");
          scheduleReconnect();
        } else {
          setConnectionState("idle", "Live feed đang tắt");
        }
      });
    }

    function stopLiveFeed() {
      wanted = false;
      request = null;
      if (reconnectTimer) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      if (socket) {
        const currentSocket = socket;
        socket = null;
        currentSocket.close();
      }
      setConnectionState("idle", "Live feed đang tắt");
      if (elements.liveNextRefresh) elements.liveNextRefresh.textContent = "Chờ kết nối stream";
      setServiceStatus("API đang hoạt động");
    }

    return Object.freeze({
      connect: (nextRequest) => connectLiveFeed(nextRequest),
      reconnect: () => {
        if (wanted && request) connectLiveFeed(request, true);
      },
      stop: stopLiveFeed,
      renderSnapshot: renderLiveSnapshot,
      isWanted: () => wanted,
      canRetry: () => Boolean(wanted && request && (state === "stale" || state === "error")),
    });
  }

  // --- ATSMatrix Multi-Agent Neural Visualizer --------------------------------
  class ATSMatrixVisualizer {
    constructor(canvas, options = {}) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.onNodeSelected = options.onNodeSelected || (() => {});
      this.selectedNodeId = null;
      this.hoveredNodeId = null;

      // Swarm state data
      this.swarmData = null;
      this.deribitTelemetry = null;
      this.botStatus = null;

      // Nodes definition
      this.nodes = [];
      this.edges = [];
      this.particles = [];
      this.animFrameId = null;
      this.lastTimestamp = 0;

      this.initNodes();
      this.initEdges();
      this.setupCanvas();
      this.bindEvents();
      this.startAnimation();
    }

    initNodes() {
      this.nodes = [
        {
          id: "research",
          tier: 0,
          label: "Research Agent",
          sublabel: "Market Regime",
          icon: "🔬",
          color: "#a855f7",
          status: "IDLE",
          metricText: "Scanning IV/RV...",
          radius: 36,
          pulse: 0,
          active: true,
        },
        {
          id: "trader_condor",
          tier: 1,
          strategy: "IRON_CONDOR",
          label: "Iron Condor",
          sublabel: "Neutral Theta",
          icon: "🦅",
          color: "#38bdf8",
          status: "STANDBY",
          metricText: "Score: --",
          radius: 26,
          pulse: 0,
          active: false,
        },
        {
          id: "trader_wheel",
          tier: 1,
          strategy: "WHEEL",
          label: "The Wheel",
          sublabel: "Cash-Secured",
          icon: "🔄",
          color: "#10b981",
          status: "STANDBY",
          metricText: "Score: --",
          radius: 26,
          pulse: 0,
          active: false,
        },
        {
          id: "trader_vertical",
          tier: 1,
          strategy: "VERTICAL_SPREAD",
          label: "Vertical Spread",
          sublabel: "Directional",
          icon: "📈",
          color: "#f59e0b",
          status: "STANDBY",
          metricText: "Score: --",
          radius: 26,
          pulse: 0,
          active: false,
        },
        {
          id: "trader_butterfly",
          tier: 1,
          strategy: "IRON_BUTTERFLY",
          label: "Iron Fly",
          sublabel: "Pin Volatility",
          icon: "🦋",
          color: "#ec4899",
          status: "STANDBY",
          metricText: "Score: --",
          radius: 26,
          pulse: 0,
          active: false,
        },
        {
          id: "trader_calendar",
          tier: 1,
          strategy: "CALENDAR_SPREAD",
          label: "Calendar Spread",
          sublabel: "Term Structure",
          icon: "📅",
          color: "#8b5cf6",
          status: "STANDBY",
          metricText: "Score: --",
          radius: 26,
          pulse: 0,
          active: false,
        },
        {
          id: "trader_long_vol",
          tier: 1,
          strategy: "LONG_VOL",
          label: "Long Vol",
          sublabel: "Convex Vega",
          icon: "⚡",
          color: "#f43f5e",
          status: "STANDBY",
          metricText: "Score: --",
          radius: 26,
          pulse: 0,
          active: false,
        },
        {
          id: "risk",
          tier: 2,
          label: "Risk Engine",
          sublabel: "60% Margin Cap",
          icon: "🛡️",
          color: "#06b6d4",
          status: "READY",
          metricText: "Cap: 60%",
          radius: 34,
          pulse: 0,
          active: true,
        },
        {
          id: "verdict",
          tier: 3,
          label: "Verdict Agent",
          sublabel: "Autonomous Gate",
          icon: "⚖️",
          color: "#eab308",
          status: "READY",
          metricText: "Auto-Approve",
          radius: 34,
          pulse: 0,
          active: true,
        },
        {
          id: "deribit",
          tier: 4,
          label: "Deribit Broker",
          sublabel: "Execution Engine",
          icon: "🏛️",
          color: "#3ca572",
          status: "CONNECTED",
          metricText: "Paper / Testnet",
          radius: 36,
          pulse: 0,
          active: true,
        },
      ];
    }

    initEdges() {
      this.edges = [];
      const traders = this.nodes.filter((n) => n.tier === 1);
      traders.forEach((t) => {
        this.edges.push({ from: "research", to: t.id, active: false, weight: 1 });
      });
      traders.forEach((t) => {
        this.edges.push({ from: t.id, to: "risk", active: false, weight: 1 });
      });
      this.edges.push({ from: "risk", to: "verdict", active: true, weight: 2 });
      this.edges.push({ from: "verdict", to: "deribit", active: true, weight: 2 });
    }

    setupCanvas() {
      const rect = this.canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      this.width = rect.width || 900;
      this.height = Math.max(480, rect.height || 500);

      this.canvas.width = this.width * dpr;
      this.canvas.height = this.height * dpr;
      this.ctx.resetTransform();
      this.ctx.scale(dpr, dpr);

      this.layoutNodes();
    }

    layoutNodes() {
      const w = this.width;
      const h = this.height;

      const tierX = {
        0: w * 0.10,
        1: w * 0.36,
        2: w * 0.62,
        3: w * 0.79,
        4: w * 0.93,
      };

      const resNode = this.nodes.find((n) => n.id === "research");
      if (resNode) {
        resNode.x = tierX[0];
        resNode.y = h * 0.5;
      }

      const traders = this.nodes.filter((n) => n.tier === 1);
      const topPadding = 60;
      const bottomPadding = 60;
      const traderHeight = h - topPadding - bottomPadding;
      const step = traderHeight / (traders.length - 1);
      traders.forEach((t, idx) => {
        t.x = tierX[1];
        t.y = topPadding + idx * step;
      });

      const riskNode = this.nodes.find((n) => n.id === "risk");
      if (riskNode) {
        riskNode.x = tierX[2];
        riskNode.y = h * 0.5;
      }

      const verdNode = this.nodes.find((n) => n.id === "verdict");
      if (verdNode) {
        verdNode.x = tierX[3];
        verdNode.y = h * 0.5;
      }

      const derNode = this.nodes.find((n) => n.id === "deribit");
      if (derNode) {
        derNode.x = tierX[4];
        derNode.y = h * 0.5;
      }
    }

    updateState(statusData) {
      if (!statusData) return;
      this.botStatus = statusData;
      this.swarmData = statusData.swarm || null;
      this.deribitTelemetry = statusData.deribit_telemetry || null;

      const swarm = this.swarmData;
      const regime = swarm ? swarm.regime : null;
      const candidates = (swarm && swarm.candidates) || [];
      const verdict = swarm ? swarm.last_verdict : null;

      const resNode = this.nodes.find((n) => n.id === "research");
      if (resNode) {
        if (regime) {
          const trend = regime.trend || "NEUTRAL";
          const vol = regime.volatility || "NORMAL";
          resNode.status = "ACTIVE";
          resNode.metricText = `${trend} / ${vol}`;
          resNode.pulse = 1.0;
        } else {
          resNode.status = "IDLE";
          resNode.metricText = "Chờ quét chu kỳ";
        }
      }

      const traders = this.nodes.filter((n) => n.tier === 1);
      traders.forEach((t) => {
        const matchingCand = candidates.find(
          (c) => (c.strategy_type || "").toUpperCase() === t.strategy
        );
        if (matchingCand) {
          t.active = true;
          t.status = "CANDIDATE";
          t.metricText = `Score: ${matchingCand.score ? matchingCand.score.toFixed(1) : "--"}`;
          t.candidate = matchingCand;
          t.pulse = 0.8;
        } else if (regime && regime.favored_strategies && regime.favored_strategies.includes(t.strategy)) {
          t.active = true;
          t.status = "FAVORED";
          t.metricText = "Favored";
        } else {
          t.active = false;
          t.status = "STANDBY";
          t.metricText = "Standby";
          t.candidate = null;
        }
      });

      this.edges.forEach((e) => {
        if (e.from === "research") {
          const targetNode = this.nodes.find((n) => n.id === e.to);
          e.active = Boolean(targetNode && targetNode.active);
        } else if (e.to === "risk") {
          const sourceNode = this.nodes.find((n) => n.id === e.from);
          e.active = Boolean(sourceNode && sourceNode.status === "CANDIDATE");
        }
      });

      const riskNode = this.nodes.find((n) => n.id === "risk");
      if (riskNode && this.deribitTelemetry) {
        const util = this.deribitTelemetry.margin_utilization_pct || 0;
        riskNode.metricText = `PMM: ${util.toFixed(1)}% / 60%`;
        riskNode.status = util > 60 ? "BREACH" : "SAFE";
      }

      const verdNode = this.nodes.find((n) => n.id === "verdict");
      if (verdNode) {
        if (verdict) {
          const approved = verdict.status === "APPROVED";
          verdNode.status = approved ? "APPROVED" : "REJECTED";
          verdNode.metricText = approved ? "AUTO-APPROVED" : "REJECTED";
          verdNode.color = approved ? "#3ca572" : "#ef4444";
          verdNode.pulse = 1.0;
        } else {
          verdNode.status = "READY";
          verdNode.metricText = "Auto-Approve";
          verdNode.color = "#eab308";
        }
      }

      const derNode = this.nodes.find((n) => n.id === "deribit");
      if (derNode && this.deribitTelemetry) {
        const eq = this.deribitTelemetry.equity_usd || 0;
        derNode.metricText = `$${eq.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
        derNode.status = this.deribitTelemetry.connected ? "LIVE" : "PAPER";
      }

      if (candidates.length > 0) {
        this.spawnParticleBurst();
      }
    }

    spawnParticleBurst() {
      const activeTraders = this.nodes.filter((n) => n.tier === 1 && n.active);
      activeTraders.forEach((t) => {
        this.particles.push({ fromId: "research", toId: t.id, color: t.color, speed: 1.2, progress: 0.0 });
        setTimeout(() => {
          this.particles.push({ fromId: t.id, toId: "risk", color: "#06b6d4", speed: 1.4, progress: 0.0 });
        }, 400);
      });

      setTimeout(() => {
        this.particles.push({ fromId: "risk", toId: "verdict", color: "#eab308", speed: 1.6, progress: 0.0 });
      }, 800);

      setTimeout(() => {
        this.particles.push({ fromId: "verdict", toId: "deribit", color: "#3ca572", speed: 1.8, progress: 0.0 });
      }, 1200);
    }

    startAnimation() {
      const render = (timestamp) => {
        const dt = (timestamp - (this.lastTimestamp || timestamp)) / 1000;
        this.lastTimestamp = timestamp;

        this.update(dt);
        this.draw();

        this.animFrameId = requestAnimationFrame(render);
      };
      this.animFrameId = requestAnimationFrame(render);
    }

    update(dt) {
      this.nodes.forEach((n) => {
        if (n.pulse > 0) {
          n.pulse = Math.max(0, n.pulse - dt * 0.5);
        }
      });

      for (let i = this.particles.length - 1; i >= 0; i--) {
        const p = this.particles[i];
        p.progress += dt * p.speed;
        if (p.progress >= 1.0) {
          this.particles.splice(i, 1);
        }
      }

      if (this.particles.length < 8 && Math.random() < 0.05) {
        const activeEdges = this.edges.filter((e) => e.active);
        if (activeEdges.length > 0) {
          const edge = activeEdges[Math.floor(Math.random() * activeEdges.length)];
          this.particles.push({ fromId: edge.from, toId: edge.to, color: "#38bdf8", speed: 0.6 + Math.random() * 0.5, progress: 0.0 });
        }
      }
    }

    draw() {
      const ctx = this.ctx;
      const w = this.width;
      const h = this.height;

      ctx.fillStyle = "#0a0f18";
      ctx.fillRect(0, 0, w, h);

      this.drawGrid(ctx, w, h);
      this.drawStageHeaders(ctx, w, h);
      this.edges.forEach((edge) => this.drawEdge(ctx, edge));
      this.particles.forEach((p) => this.drawParticle(ctx, p));
      this.nodes.forEach((node) => this.drawNode(ctx, node));
    }

    drawGrid(ctx, w, h) {
      ctx.save();
      ctx.strokeStyle = "rgba(30, 41, 59, 0.4)";
      ctx.lineWidth = 1;
      const gridSize = 40;

      for (let x = 0; x < w; x += gridSize) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, h);
        ctx.stroke();
      }
      for (let y = 0; y < h; y += gridSize) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
      }
      ctx.restore();
    }

    drawStageHeaders(ctx, w, h) {
      ctx.save();
      ctx.font = "bold 10px 'JetBrains Mono', monospace, sans-serif";
      ctx.fillStyle = "#475569";
      ctx.textAlign = "center";

      const headers = [
        { label: "STAGE 1: RESEARCH", x: w * 0.10 },
        { label: "STAGE 2: TRADER POOL", x: w * 0.36 },
        { label: "STAGE 3: RISK ENGINE", x: w * 0.62 },
        { label: "STAGE 4: VERDICT", x: w * 0.79 },
        { label: "STAGE 5: BROKER", x: w * 0.93 },
      ];

      headers.forEach((hdr) => {
        ctx.fillText(hdr.label, hdr.x, 24);
      });
      ctx.restore();
    }

    drawEdge(ctx, edge) {
      const fromNode = this.nodes.find((n) => n.id === edge.from);
      const toNode = this.nodes.find((n) => n.id === edge.to);
      if (!fromNode || !toNode) return;

      ctx.save();
      ctx.beginPath();

      const dx = (toNode.x - fromNode.x) * 0.5;
      const cp1x = fromNode.x + dx;
      const cp1y = fromNode.y;
      const cp2x = toNode.x - dx;
      const cp2y = toNode.y;

      ctx.moveTo(fromNode.x, fromNode.y);
      ctx.bezierCurveTo(cp1x, cp1y, cp2x, cp2y, toNode.x, toNode.y);

      if (edge.active) {
        ctx.strokeStyle = "rgba(56, 189, 248, 0.6)";
        ctx.lineWidth = 2;
        ctx.shadowColor = "#38bdf8";
        ctx.shadowBlur = 6;
      } else {
        ctx.strokeStyle = "rgba(30, 41, 59, 0.4)";
        ctx.lineWidth = 1;
        ctx.shadowBlur = 0;
      }

      ctx.stroke();
      ctx.restore();
    }

    drawParticle(ctx, particle) {
      const fromNode = this.nodes.find((n) => n.id === particle.fromId);
      const toNode = this.nodes.find((n) => n.id === particle.toId);
      if (!fromNode || !toNode) return;

      const t = particle.progress;
      const dx = (toNode.x - fromNode.x) * 0.5;
      const cp1x = fromNode.x + dx;
      const cp1y = fromNode.y;
      const cp2x = toNode.x - dx;
      const cp2y = toNode.y;

      const invT = 1 - t;
      const x =
        Math.pow(invT, 3) * fromNode.x +
        3 * Math.pow(invT, 2) * t * cp1x +
        3 * invT * Math.pow(t, 2) * cp2x +
        Math.pow(t, 3) * toNode.x;
      const y =
        Math.pow(invT, 3) * fromNode.y +
        3 * Math.pow(invT, 2) * t * cp1y +
        3 * invT * Math.pow(t, 2) * cp2y +
        Math.pow(t, 3) * toNode.y;

      ctx.save();
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fillStyle = particle.color;
      ctx.shadowColor = particle.color;
      ctx.shadowBlur = 10;
      ctx.fill();
      ctx.restore();
    }

    drawNode(ctx, node) {
      const isHovered = this.hoveredNodeId === node.id;
      const isSelected = this.selectedNodeId === node.id;

      ctx.save();

      if (node.pulse > 0) {
        ctx.beginPath();
        const pulseR = node.radius + 14 * (1 - node.pulse);
        ctx.arc(node.x, node.y, pulseR, 0, Math.PI * 2);
        ctx.strokeStyle = node.color;
        ctx.lineWidth = 2 * node.pulse;
        ctx.globalAlpha = node.pulse;
        ctx.stroke();
        ctx.globalAlpha = 1.0;
      }

      if (isSelected || isHovered) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, node.radius + 6, 0, Math.PI * 2);
        ctx.strokeStyle = isSelected ? "#38bdf8" : "rgba(255, 255, 255, 0.4)";
        ctx.lineWidth = isSelected ? 3 : 1.5;
        ctx.shadowColor = isSelected ? "#38bdf8" : "#fff";
        ctx.shadowBlur = 12;
        ctx.stroke();
      }

      ctx.beginPath();
      ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
      ctx.fillStyle = node.active ? "#131c26" : "#0d131a";
      ctx.fill();

      ctx.strokeStyle = node.active ? node.color : "#334155";
      ctx.lineWidth = node.active ? 2.5 : 1.5;
      if (node.active) {
        ctx.shadowColor = node.color;
        ctx.shadowBlur = 8;
      }
      ctx.stroke();
      ctx.shadowBlur = 0;

      ctx.font = `${Math.floor(node.radius * 0.7)}px sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(node.icon, node.x, node.y - 2);

      ctx.font = "bold 11px system-ui, -apple-system, sans-serif";
      ctx.fillStyle = node.active ? "#f1f5f9" : "#64748b";
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillText(node.label, node.x, node.y + node.radius + 6);

      ctx.font = "9px 'JetBrains Mono', monospace, sans-serif";
      ctx.fillStyle = node.active ? node.color : "#475569";
      ctx.fillText(node.metricText, node.x, node.y + node.radius + 20);

      if (node.status && node.status !== "STANDBY" && node.status !== "IDLE") {
        this.drawStatusPill(ctx, node);
      }

      ctx.restore();
    }

    drawStatusPill(ctx, node) {
      ctx.save();
      const text = node.status;
      ctx.font = "bold 8px 'JetBrains Mono', monospace";
      const metrics = ctx.measureText(text);
      const pillW = metrics.width + 10;
      const pillH = 14;
      const pillX = node.x - pillW / 2;
      const pillY = node.y - node.radius - 12;

      ctx.beginPath();
      ctx.roundRect(pillX, pillY, pillW, pillH, 7);
      ctx.fillStyle = node.active ? "#0f172a" : "#1e293b";
      ctx.fill();
      ctx.strokeStyle = node.color;
      ctx.lineWidth = 1;
      ctx.stroke();

      ctx.fillStyle = node.color;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(text, node.x, pillY + pillH / 2);
      ctx.restore();
    }

    bindEvents() {
      if (window.ResizeObserver) {
        this.resizeObserver = new ResizeObserver(() => {
          this.setupCanvas();
        });
        this.resizeObserver.observe(this.canvas.parentElement || this.canvas);
      } else {
        window.addEventListener("resize", () => this.setupCanvas());
      }

      this.canvas.addEventListener("mousemove", (e) => {
        const rect = this.canvas.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;

        let found = null;
        for (const node of this.nodes) {
          const dist = Math.hypot(node.x - mouseX, node.y - mouseY);
          if (dist <= node.radius + 8) {
            found = node;
            break;
          }
        }

        if (found) {
          this.canvas.style.cursor = "pointer";
          this.hoveredNodeId = found.id;
        } else {
          this.canvas.style.cursor = "default";
          this.hoveredNodeId = null;
        }
      });

      this.canvas.addEventListener("click", (e) => {
        const rect = this.canvas.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;

        let clicked = null;
        for (const node of this.nodes) {
          const dist = Math.hypot(node.x - mouseX, node.y - mouseY);
          if (dist <= node.radius + 8) {
            clicked = node;
            break;
          }
        }

        if (clicked) {
          this.selectedNodeId = clicked.id;
          this.onNodeSelected(clicked, {
            node: clicked,
            swarm: this.swarmData,
            telemetry: this.deribitTelemetry,
            bot: this.botStatus,
          });
        }
      });
    }

    destroy() {
      if (this.animFrameId) {
        cancelAnimationFrame(this.animFrameId);
      }
      if (this.resizeObserver) {
        this.resizeObserver.disconnect();
      }
    }
  }

  // --- ATSMatrix Multi-Agent Neural Desk Controller --------------------------

  function initBotDesk() {
    const badge = document.getElementById("bot-status-badge");
    const btnToggle = document.getElementById("bot-btn-toggle");
    const btnCycle = document.getElementById("bot-btn-cycle");
    const btnClose = document.getElementById("bot-btn-close");
    const btnReset = document.getElementById("bot-btn-reset");

    // Top Deribit Telemetry Strip
    const statEquity = document.getElementById("bot-stat-equity");
    const statCrypto = document.getElementById("bot-stat-crypto");
    const statCash = document.getElementById("bot-stat-cash");
    const statInitMargin = document.getElementById("bot-stat-initial-margin");
    const statMargin = document.getElementById("bot-stat-margin");
    const marginMeter = document.getElementById("bot-margin-meter");
    const statUnrealized = document.getElementById("bot-stat-unrealized");
    const statDelta = document.getElementById("bot-stat-delta");

    // Canvas Floating HUD
    const hudRegime = document.getElementById("hud-regime-val");
    const hudFavored = document.getElementById("hud-favored-val");
    const hudVerdict = document.getElementById("hud-verdict-val");

    // Node Inspector Drawer
    const drawerEl = document.getElementById("node-inspector-drawer");
    const drawerCloseBtn = document.getElementById("drawer-close-btn");
    const drawerIcon = document.getElementById("drawer-node-icon");
    const drawerTitle = document.getElementById("drawer-node-title");
    const drawerRole = document.getElementById("drawer-node-role");
    const drawerBody = document.getElementById("drawer-body-content");

    // Tab Switcher
    const tabBtnCanvas = document.getElementById("tab-btn-canvas");
    const tabBtnEquity = document.getElementById("tab-btn-equity");
    const tabBtnPositions = document.getElementById("tab-btn-positions");
    const viewCanvas = document.getElementById("view-swarm-canvas");
    const viewEquity = document.getElementById("view-swarm-equity");
    const viewPositions = document.getElementById("view-swarm-positions");

    // Positions & Legs
    const condorId = document.getElementById("bot-condor-id");
    const tpTarget = document.getElementById("bot-tp-target");
    const tpFill = document.getElementById("bot-tp-fill");
    const legsBody = document.getElementById("bot-legs-body");

    // Terminal
    const terminalLog = document.getElementById("swarm-terminal-log");
    const terminalClearBtn = document.getElementById("terminal-clear-btn");
    const messageText = document.getElementById("bot-message-text");
    const statCycleTime = document.getElementById("bot-stat-cycle-time");

    // Equity Chart Elements
    const equityCanvas = document.getElementById("swarm-equity-canvas");
    const eqCurrent = document.getElementById("eq-metric-current");
    const eqPeak = document.getElementById("eq-metric-peak");
    const eqDrawdown = document.getElementById("eq-metric-drawdown");
    const eqMargin = document.getElementById("eq-metric-margin");
    const timeframeBtns = document.querySelectorAll(".btn-timeframe");

    if (!badge || !btnToggle) return; // Not on page

    let isRunning = false;
    let botSocket = null;
    let visualizer = null;
    let currentTimeframe = "1d";
    let lastRenderedCycleTime = null;
    let latestState = null;

    function formatCurrency(val) {
      if (val === null || val === undefined) return "$0.00";
      const num = Number(val);
      const sign = num < 0 ? "-" : "";
      return `${sign}$${Math.abs(num).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }

    function createDrawerCard(title) {
      const card = document.createElement("div");
      card.className = "drawer-card";
      const t = document.createElement("div");
      t.className = "drawer-card-title";
      t.textContent = title;
      card.appendChild(t);
      return card;
    }

    function addDrawerRow(card, label, value, valueStyle = {}) {
      const row = document.createElement("div");
      row.className = "drawer-stat-row";
      const span = document.createElement("span");
      span.textContent = label;
      const strong = document.createElement("strong");
      strong.textContent = value;
      Object.assign(strong.style, valueStyle);
      row.appendChild(span);
      row.appendChild(strong);
      card.appendChild(row);
    }

    // Terminal Logging
    function logTerminal(tag, message, type = "system") {
      if (!terminalLog) return;
      const now = new Date();
      const timeStr = now.toTimeString().split(" ")[0];

      const line = document.createElement("div");
      line.className = "terminal-line";

      const timeSpan = document.createElement("span");
      timeSpan.className = "log-time";
      timeSpan.textContent = `[${timeStr}]`;

      const tagSpan = document.createElement("span");
      tagSpan.className = `log-tag log-tag-${type}`;
      tagSpan.textContent = tag;

      const textNode = document.createTextNode(` ${message}`);

      line.appendChild(timeSpan);
      line.appendChild(tagSpan);
      line.appendChild(textNode);

      terminalLog.appendChild(line);

      while (terminalLog.children.length > 100) {
        terminalLog.removeChild(terminalLog.firstChild);
      }

      terminalLog.scrollTop = terminalLog.scrollHeight;
    }

    if (terminalClearBtn) {
      terminalClearBtn.addEventListener("click", () => {
        if (terminalLog) terminalLog.textContent = "";
      });
    }

    // Initialize ATSMatrix Canvas Visualizer
    const canvasEl = document.getElementById("swarm-neural-canvas");
    if (canvasEl) {
      visualizer = new ATSMatrixVisualizer(canvasEl, {
        onNodeSelected: (node, meta) => renderNodeInspector(node, meta),
      });
    }

    // Drawer Inspector Logic
    function renderNodeInspector(node, meta) {
      if (!drawerEl || !drawerBody) return;

      drawerEl.classList.add("open");
      drawerEl.setAttribute("aria-hidden", "false");

      if (drawerIcon) drawerIcon.textContent = node.icon;
      if (drawerTitle) drawerTitle.textContent = node.label;
      if (drawerRole) drawerRole.textContent = node.sublabel;

      const swarm = (meta && meta.swarm) || {};
      const regime = swarm.regime || null;
      const candidates = swarm.candidates || [];
      const verdict = swarm.last_verdict || null;
      const telemetry = (meta && meta.telemetry) || {};

      drawerBody.textContent = "";

      if (node.id === "research") {
        const cardRegime = createDrawerCard("Phân tích Market Regime");
        addDrawerRow(cardRegime, "Xu hướng (Trend):", regime ? regime.trend : "NEUTRAL");
        addDrawerRow(cardRegime, "Biến động (Vol):", regime ? regime.volatility : "NORMAL");
        addDrawerRow(cardRegime, "Cấu trúc kỳ hạn:", regime ? regime.term_structure : "FLAT");
        addDrawerRow(cardRegime, "Độ lệch (Skew):", regime ? regime.skew : "BALANCED");
        drawerBody.appendChild(cardRegime);

        const cardMetrics = createDrawerCard("Chỉ số định lượng (Quantitative)");
        const metrics = regime ? regime.metrics || {} : {};
        addDrawerRow(cardMetrics, "HV 20-Day:", metrics.hv_20 ? (metrics.hv_20 * 100).toFixed(1) + "%" : "--");
        addDrawerRow(cardMetrics, "ATM IV 30-Day:", metrics.atm_iv_30 ? (metrics.atm_iv_30 * 100).toFixed(1) + "%" : "--");
        addDrawerRow(cardMetrics, "IV - RV Spread:", metrics.iv_rv_spread ? (metrics.iv_rv_spread * 100).toFixed(1) + "%" : "--");
        addDrawerRow(cardMetrics, "SMA20 Trend Slope:", metrics.trend_slope ? (metrics.trend_slope * 100).toFixed(2) + "%" : "--");
        drawerBody.appendChild(cardMetrics);

        if (regime && regime.synthesis) {
          const cardThesis = createDrawerCard("Gemini LLM Thesis");
          const thesisText = document.createElement("div");
          thesisText.className = "drawer-thesis-text";
          thesisText.textContent = regime.synthesis;
          cardThesis.appendChild(thesisText);
          drawerBody.appendChild(cardThesis);
        }
      } else if (node.tier === 1) {
        const strat = node.strategy;
        const matchingCand = candidates.find((c) => (c.strategy_type || "").toUpperCase() === strat);

        const cardTrader = createDrawerCard(`Chiến lược ${node.label}`);
        addDrawerRow(cardTrader, "Trạng thái:", node.status);
        addDrawerRow(cardTrader, "Điểm tín hiệu (Score):", matchingCand && matchingCand.score ? matchingCand.score.toFixed(1) : "--");
        addDrawerRow(cardTrader, "Premium / Net Credit:", matchingCand ? formatCurrency(matchingCand.net_credit_or_debit || matchingCand.entry_credit || 0) : "--");
        addDrawerRow(cardTrader, "Lợi nhuận tối đa:", matchingCand ? formatCurrency(matchingCand.max_profit || 0) : "--");
        addDrawerRow(cardTrader, "Rủi ro tối đa:", matchingCand ? formatCurrency(matchingCand.max_loss || 0) : "--");
        drawerBody.appendChild(cardTrader);

        if (matchingCand && Array.isArray(matchingCand.legs) && matchingCand.legs.length > 0) {
          const cardLegs = createDrawerCard("Cấu trúc chân hợp đồng (Legs)");
          matchingCand.legs.forEach((l) => {
            const roleStr = `${l.role || l.side} ${l.strike || ""} ${l.option_type || ""}`;
            const valStr = `${l.qty || 1}x @ $${(l.mark_price || l.entry_price || 0).toFixed(2)}`;
            addDrawerRow(cardLegs, roleStr, valStr);
          });
          drawerBody.appendChild(cardLegs);
        }
      } else if (node.id === "risk") {
        const cardRisk = createDrawerCard("Đánh giá Rủi ro & Margin");
        const pmm = telemetry.margin_utilization_pct || 0;
        addDrawerRow(cardRisk, "Margin Hiện tại:", formatCurrency(telemetry.initial_margin_usd || 0));
        addDrawerRow(cardRisk, "Sử dụng Margin (PMM):", `${pmm.toFixed(1)}% / 60% CAP`);
        addDrawerRow(cardRisk, "Chuẩn Lot size:", "0.1 BTC / 1.0 ETH");
        addDrawerRow(cardRisk, "Giới hạn Delta Portfolio:", "± 5.0 Δ");
        addDrawerRow(
          cardRisk,
          "Trạng thái Engine:",
          pmm > 60 ? "CẢNH BÁO VƯỢT CAP" : "AN TOÀN (SAFE)",
          { color: pmm > 60 ? "#ef4444" : "#3ca572" }
        );
        drawerBody.appendChild(cardRisk);
      } else if (node.id === "verdict") {
        const cardVerd = createDrawerCard("Quyết định Autonomous Swarm");
        const approved = verdict && verdict.status === "APPROVED";
        addDrawerRow(
          cardVerd,
          "Phán quyết (Verdict):",
          verdict ? verdict.status : "READY",
          { color: approved ? "#3ca572" : "#eab308" }
        );
        addDrawerRow(cardVerd, "Chế độ:", "TỰ ĐỘNG PHÊ DUYỆT (AUTONOMOUS)");
        addDrawerRow(cardVerd, "Chiến lược chọn:", verdict && verdict.selected_strategy ? verdict.selected_strategy : "--");
        addDrawerRow(cardVerd, "Lý do / Ghi chú:", verdict && verdict.reason ? verdict.reason : "Chờ tín hiệu từ Trader Pool");
        drawerBody.appendChild(cardVerd);
      } else if (node.id === "deribit") {
        const cardDer = createDrawerCard("Deribit Broker Telemetry");
        addDrawerRow(cardDer, "Kết nối:", telemetry.connected ? "LIVE DERIBIT" : "LOCAL PAPER TESTNET");
        addDrawerRow(cardDer, "Vốn khả dụng (USD):", formatCurrency(telemetry.equity_usd || 10000));
        addDrawerRow(cardDer, "Số dư Crypto:", `${(telemetry.equity_crypto || 0).toFixed(4)} ${telemetry.currency || "BTC"}`);
        addDrawerRow(cardDer, "Vị thế mở:", `${telemetry.open_positions_count || 0} vị thế`);
        const pDel = telemetry.portfolio_delta !== undefined ? (telemetry.portfolio_delta >= 0 ? "+" : "") + telemetry.portfolio_delta.toFixed(3) + " Δ" : "+0.000 Δ";
        addDrawerRow(cardDer, "Net Portfolio Delta:", pDel);
        drawerBody.appendChild(cardDer);
      }
    }

    if (drawerCloseBtn) {
      drawerCloseBtn.addEventListener("click", () => {
        if (drawerEl) {
          drawerEl.classList.remove("open");
          drawerEl.setAttribute("aria-hidden", "true");
        }
      });
    }

    // View Switching Logic
    function switchTab(target) {
      [tabBtnCanvas, tabBtnEquity, tabBtnPositions].forEach((btn) => {
        if (btn) btn.classList.remove("active");
      });
      [viewCanvas, viewEquity, viewPositions].forEach((v) => {
        if (v) v.classList.remove("active");
      });

      if (target === "canvas") {
        if (tabBtnCanvas) tabBtnCanvas.classList.add("active");
        if (viewCanvas) viewCanvas.classList.add("active");
        if (visualizer) visualizer.setupCanvas();
      } else if (target === "equity") {
        if (tabBtnEquity) tabBtnEquity.classList.add("active");
        if (viewEquity) viewEquity.classList.add("active");
        fetchAndRenderEquity(currentTimeframe);
      } else if (target === "positions") {
        if (tabBtnPositions) tabBtnPositions.classList.add("active");
        if (viewPositions) viewPositions.classList.add("active");
      }
    }

    if (tabBtnCanvas) tabBtnCanvas.addEventListener("click", () => switchTab("canvas"));
    if (tabBtnEquity) tabBtnEquity.addEventListener("click", () => switchTab("equity"));
    if (tabBtnPositions) tabBtnPositions.addEventListener("click", () => switchTab("positions"));

    // Timeframe selector
    timeframeBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        timeframeBtns.forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        currentTimeframe = btn.getAttribute("data-timeframe") || "1d";
        fetchAndRenderEquity(currentTimeframe);
      });
    });

    // Equity Chart Fetch & Render
    async function fetchAndRenderEquity(tf) {
      if (!equityCanvas) return;
      try {
        const res = await fetch(`/api/v1/bot/equity-history?timeframe=${tf}`);
        if (!res.ok) return;
        const data = await res.json();
        const snapshots = data.snapshots || [];
        renderEquityCanvas(snapshots);
      } catch (err) {
        console.warn("Error fetching equity history:", err);
      }
    }

    function renderEquityCanvas(snapshots) {
      if (!equityCanvas) return;
      const ctx = equityCanvas.getContext("2d");
      const rect = equityCanvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      const w = rect.width || 800;
      const h = 320;

      equityCanvas.width = w * dpr;
      equityCanvas.height = h * dpr;
      ctx.resetTransform();
      ctx.scale(dpr, dpr);

      // Clear
      ctx.fillStyle = "#0a0f18";
      ctx.fillRect(0, 0, w, h);

      if (snapshots.length === 0) {
        ctx.fillStyle = "#64748b";
        ctx.font = "italic 13px system-ui, sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("Chưa có dữ liệu lịch sử vốn cho khoảng thời gian này.", w / 2, h / 2);
        return;
      }

      // Compute stats
      const equities = snapshots.map((s) => s.equity_usd || 10000);
      const minEq = Math.min(...equities) * 0.998;
      const maxEq = Math.max(...equities) * 1.002;
      const curVal = equities[equities.length - 1];
      const peakVal = Math.max(...equities);
      const maxDd = peakVal > 0 ? ((peakVal - Math.min(...equities)) / peakVal) * 100 : 0;
      const maxMargin = Math.max(...snapshots.map((s) => s.margin_utilization_pct || 0));

      if (eqCurrent) eqCurrent.textContent = formatCurrency(curVal);
      if (eqPeak) eqPeak.textContent = formatCurrency(peakVal);
      if (eqDrawdown) eqDrawdown.textContent = `${maxDd.toFixed(2)}%`;
      if (eqMargin) eqMargin.textContent = `${maxMargin.toFixed(1)}%`;

      // Plot setup
      const padL = 60;
      const padR = 24;
      const padT = 24;
      const padB = 36;
      const plotW = w - padL - padR;
      const plotH = h - padT - padB;

      // Draw grid
      ctx.strokeStyle = "rgba(30, 41, 59, 0.4)";
      ctx.lineWidth = 1;
      const ySteps = 4;
      ctx.font = "10px 'JetBrains Mono', monospace";
      ctx.fillStyle = "#64748b";
      ctx.textAlign = "right";

      for (let i = 0; i <= ySteps; i++) {
        const y = padT + (plotH / ySteps) * i;
        const val = maxEq - ((maxEq - minEq) / ySteps) * i;
        ctx.beginPath();
        ctx.moveTo(padL, y);
        ctx.lineTo(w - padR, y);
        ctx.stroke();
        ctx.fillText(formatCurrency(val), padL - 8, y + 3);
      }

      // Compute points
      const points = snapshots.map((s, idx) => {
        const x = snapshots.length > 1 ? padL + (plotW / (snapshots.length - 1)) * idx : padL + plotW / 2;
        const normY = maxEq === minEq ? 0.5 : (s.equity_usd - minEq) / (maxEq - minEq);
        const y = padT + plotH * (1 - normY);
        return { x, y, data: s };
      });

      // Draw Gradient Fill
      const grad = ctx.createLinearGradient(0, padT, 0, padT + plotH);
      grad.addColorStop(0, "rgba(56, 189, 248, 0.3)");
      grad.addColorStop(1, "rgba(56, 189, 248, 0.0)");

      ctx.beginPath();
      ctx.moveTo(points[0].x, padT + plotH);
      points.forEach((p) => ctx.lineTo(p.x, p.y));
      ctx.lineTo(points[points.length - 1].x, padT + plotH);
      ctx.closePath();
      ctx.fillStyle = grad;
      ctx.fill();

      // Draw Line
      ctx.beginPath();
      ctx.moveTo(points[0].x, points[0].y);
      for (let i = 1; i < points.length; i++) {
        ctx.lineTo(points[i].x, points[i].y);
      }
      ctx.strokeStyle = "#38bdf8";
      ctx.lineWidth = 2.5;
      ctx.shadowColor = "#38bdf8";
      ctx.shadowBlur = 8;
      ctx.stroke();
      ctx.shadowBlur = 0;

      // Draw dots on points
      points.forEach((p) => {
        ctx.beginPath();
        ctx.arc(p.x, p.y, 3.5, 0, Math.PI * 2);
        ctx.fillStyle = "#0f172a";
        ctx.fill();
        ctx.strokeStyle = "#38bdf8";
        ctx.lineWidth = 2;
        ctx.stroke();
      });
    }

    // Render Full Bot State
    function renderBotState(data) {
      if (!data) return;
      latestState = data;
      const ctrl = data.control || {};
      const port = data.portfolio || {};
      const margin = data.margin || {};
      const active = data.active_condor;
      const deribit = data.deribit_telemetry || {};
      const swarm = data.swarm || {};

      // Running State
      isRunning = Boolean(ctrl.is_running);
      if (isRunning) {
        badge.textContent = "RUNNING";
        badge.className = "bot-badge bot-badge-running";
        btnToggle.textContent = "Dừng Bot (Stop)";
        btnToggle.classList.add("running");
      } else {
        badge.textContent = "IDLE";
        badge.className = "bot-badge bot-badge-idle";
        btnToggle.textContent = "Bật Bot (Start)";
        btnToggle.classList.remove("running");
      }

      // Update Deribit Top Strip
      const eqUsd = deribit.equity_usd || port.equity || 10000;
      const eqCry = deribit.equity_crypto || 0.1667;
      if (statEquity) statEquity.textContent = formatCurrency(eqUsd);
      if (statCrypto) statCrypto.textContent = `${eqCry.toFixed(4)} ${deribit.currency || "BTC"}`;
      if (statCash) statCash.textContent = formatCurrency(deribit.balance_crypto ? deribit.balance_crypto * 60000 : port.cash_balance || 10000);
      if (statInitMargin) statInitMargin.textContent = `Init Margin: ${formatCurrency(deribit.initial_margin_usd || 0)}`;

      const util = deribit.margin_utilization_pct !== undefined ? deribit.margin_utilization_pct : margin.margin_utilization_pct || 0;
      if (statMargin && marginMeter) {
        statMargin.textContent = `${util.toFixed(1)}% `;
        const capTag = document.createElement("span");
        capTag.className = "stat-cap-tag";
        capTag.textContent = "/ 60% CAP";
        statMargin.appendChild(capTag);

        marginMeter.style.width = `${Math.min(100, Math.max(0, util))}%`;
        marginMeter.className = "bot-margin-meter";
        if (util >= 60) marginMeter.classList.add("critical");
        else if (util >= 45) marginMeter.classList.add("warning");
      }

      const pnl = port.total_unrealized_pnl || 0;
      if (statUnrealized) {
        statUnrealized.textContent = (pnl >= 0 ? "+" : "") + formatCurrency(pnl);
        statUnrealized.style.color = pnl >= 0 ? "#3ca572" : "#ef4444";
      }

      const netDel = deribit.portfolio_delta !== undefined ? deribit.portfolio_delta : 0;
      if (statDelta) {
        statDelta.textContent = `Net Delta: ${(netDel >= 0 ? "+" : "") + netDel.toFixed(2)} Δ`;
      }

      // Update Floating Canvas HUD
      if (swarm.regime && hudRegime) {
        hudRegime.textContent = `${swarm.regime.trend} | ${swarm.regime.volatility}`;
      }
      if (swarm.candidates && swarm.candidates.length > 0 && hudFavored) {
        const top = swarm.candidates[0];
        hudFavored.textContent = `${top.strategy_type} (${top.score ? top.score.toFixed(1) : "--"})`;
      }
      if (swarm.last_verdict && hudVerdict) {
        hudVerdict.textContent = swarm.last_verdict.status;
        hudVerdict.style.color = swarm.last_verdict.status === "APPROVED" ? "#3ca572" : "#ef4444";
      }

      // Update Canvas
      if (visualizer) {
        visualizer.updateState(data);
      }

      // Cycle time
      if (statCycleTime && ctrl.last_cycle_time) {
        statCycleTime.textContent = new Date(ctrl.last_cycle_time).toLocaleTimeString();
      }

      // Message bar
      if (messageText && ctrl.last_action_message) {
        messageText.textContent = ctrl.last_action_message;
      }

      // Terminal Logs on New Cycle
      if (ctrl.last_cycle_time && ctrl.last_cycle_time !== lastRenderedCycleTime) {
        lastRenderedCycleTime = ctrl.last_cycle_time;
        logTerminal("CYCLE", `Quét chu kỳ hoàn tất. Trạng thái: ${ctrl.last_cycle_status || "OK"}`, "system");

        if (swarm.regime) {
          logTerminal(
            "RESEARCH",
            `Market Regime: Trend=${swarm.regime.trend}, Vol=${swarm.regime.volatility}, Skew=${swarm.regime.skew}`,
            "research"
          );
        }
        if (swarm.candidates && swarm.candidates.length > 0) {
          const top = swarm.candidates[0];
          logTerminal(
            "TRADER_POOL",
            `Tìm thấy ${swarm.candidates.length} cơ hội. Ưu tiên: ${top.strategy_type} (Score: ${top.score.toFixed(1)})`,
            "trader"
          );
        }
        if (swarm.last_verdict) {
          const isApp = swarm.last_verdict.status === "APPROVED";
          logTerminal(
            "VERDICT",
            `${isApp ? "AUTO-APPROVED" : "REJECTED"}: ${swarm.last_verdict.selected_strategy || "Signal"} - ${swarm.last_verdict.reason || ""}`,
            isApp ? "verdict" : "reject"
          );
          if (isApp) {
            logTerminal(
              "DERIBIT",
              `Lệnh được chuyển sang Deribit Broker Adapter để thực thi tự động.`,
              "deribit"
            );
          }
        }
      }

      // Render Active Positions in Tab 3
      if (active && Array.isArray(active.legs) && active.legs.length > 0) {
        if (condorId) condorId.textContent = `${active.condor_id} (Credit: ${formatCurrency(active.entry_credit)})`;
        if (tpTarget) tpTarget.textContent = formatCurrency(active.target_profit_50);

        const target = active.target_profit_50 || 1;
        const currentUnrealized = active.unrealized_pnl || 0;
        const pct = Math.min(100, Math.max(0, (currentUnrealized / target) * 100));
        if (tpFill) tpFill.style.width = `${pct}%`;

        if (legsBody) {
          legsBody.textContent = "";
          active.legs.forEach((leg) => {
            const isShort = leg.side === "Sell";
            const roleClass = isShort ? "bot-role-short" : "bot-role-wing";
            const legPnl = leg.unrealized_pnl || 0;
            const pnlColor = legPnl >= 0 ? "#3ca572" : "#ef4444";

            const tr = document.createElement("tr");

            const tdRole = document.createElement("td");
            const span = document.createElement("span");
            span.className = `bot-role-tag ${roleClass}`;
            span.textContent = leg.role || leg.side;
            tdRole.appendChild(span);
            tr.appendChild(tdRole);

            const tdSym = document.createElement("td");
            const strong = document.createElement("strong");
            strong.textContent = leg.symbol;
            tdSym.appendChild(strong);
            tr.appendChild(tdSym);

            const tdStrike = document.createElement("td");
            tdStrike.textContent = Number(leg.strike).toLocaleString();
            tr.appendChild(tdStrike);

            const tdType = document.createElement("td");
            tdType.style.textTransform = "uppercase";
            tdType.textContent = leg.option_type;
            tr.appendChild(tdType);

            const tdSide = document.createElement("td");
            const strongSide = document.createElement("strong");
            strongSide.textContent = leg.side;
            tdSide.appendChild(strongSide);
            tr.appendChild(tdSide);

            const tdQty = document.createElement("td");
            tdQty.textContent = leg.qty;
            tr.appendChild(tdQty);

            const tdEntry = document.createElement("td");
            tdEntry.textContent = formatCurrency(leg.entry_price);
            tr.appendChild(tdEntry);

            const tdMark = document.createElement("td");
            tdMark.textContent = formatCurrency(leg.current_mark);
            tr.appendChild(tdMark);

            const tdPnl = document.createElement("td");
            tdPnl.style.color = pnlColor;
            tdPnl.style.fontWeight = "700";
            tdPnl.textContent = (legPnl >= 0 ? "+" : "") + formatCurrency(legPnl);
            tr.appendChild(tdPnl);

            legsBody.appendChild(tr);
          });
        }
      } else {
        if (condorId) condorId.textContent = "Chưa có vị thế mở";
        if (tpTarget) tpTarget.textContent = "$0.00";
        if (tpFill) tpFill.style.width = "0%";
        if (legsBody) {
          legsBody.textContent = "";
          const tr = document.createElement("tr");
          const td = document.createElement("td");
          td.colSpan = 9;
          td.className = "bot-empty-cell";
          td.textContent = "Không có vị thế option nào đang chạy. Bấm \"Quét ngay\" hoặc \"Bật Bot\" để tự động tìm cơ hội.";
          tr.appendChild(td);
          legsBody.appendChild(tr);
        }
      }
    }

    async function sendControl(action, extra = {}) {
      try {
        if (messageText) messageText.textContent = `Đang gửi lệnh ${action}...`;
        logTerminal("COMMAND", `Gửi lệnh điều khiển: ${action.toUpperCase()}`, "system");

        const res = await fetch("/api/v1/bot/control", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action, ...extra }),
        });
        const data = await res.json();
        if (data.current_status) {
          renderBotState(data.current_status);
        }
      } catch (err) {
        if (messageText) messageText.textContent = `Lỗi: ${err.message}`;
        logTerminal("ERROR", `Lỗi thực thi lệnh: ${err.message}`, "reject");
      }
    }

    // Connect WebSocket
    function connectBotStream() {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const url = `${protocol}//${window.location.host}/api/v1/bot/stream`;
      botSocket = new WebSocket(url);

      botSocket.onopen = () => {
        logTerminal("STREAM", "Đã kết nối WebSocket /api/v1/bot/stream", "system");
      };

      botSocket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          renderBotState(data);
        } catch (e) {
          console.warn("Invalid bot stream payload", e);
        }
      };

      botSocket.onclose = () => {
        logTerminal("STREAM", "Mất kết nối WebSocket. Tự động kết nối lại sau 3s...", "system");
        setTimeout(connectBotStream, 3000);
      };
    }

    // Bind Button Events
    btnToggle.addEventListener("click", () => {
      sendControl(isRunning ? "stop" : "start");
    });
    btnCycle.addEventListener("click", () => {
      sendControl("cycle");
    });
    btnClose.addEventListener("click", () => {
      if (confirm("Bạn có chắc chắn muốn đóng khẩn cấp toàn bộ vị thế bot?")) {
        sendControl("close_all");
      }
    });
    btnReset.addEventListener("click", () => {
      if (confirm("Reset lại tài khoản ảo về $10,000 và xóa hết vị thế?")) {
        sendControl("reset", { capital: 10000.0 });
      }
    });

    // Initial fetch and WS connect
    fetch("/api/v1/bot/status")
      .then((r) => r.json())
      .then((data) => {
        renderBotState(data);
        fetchAndRenderEquity(currentTimeframe);
      })
      .catch(console.warn);

    connectBotStream();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initBotDesk);
  } else {
    initBotDesk();
  }

  window.FlowSurfaceLiveDesk = Object.freeze({ createController });
})();
