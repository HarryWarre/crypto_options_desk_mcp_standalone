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

  // --- Automated Options Bot Controller -------------------------------------

  function initBotDesk() {
    const badge = document.getElementById("bot-status-badge");
    const btnToggle = document.getElementById("bot-btn-toggle");
    const btnCycle = document.getElementById("bot-btn-cycle");
    const btnClose = document.getElementById("bot-btn-close");
    const btnReset = document.getElementById("bot-btn-reset");

    const statEquity = document.getElementById("bot-stat-equity");
    const statCash = document.getElementById("bot-stat-cash");
    const statUnrealized = document.getElementById("bot-stat-unrealized");
    const statCompounded = document.getElementById("bot-stat-compounded");
    const statMargin = document.getElementById("bot-stat-margin");
    const marginMeter = document.getElementById("bot-margin-meter");
    const statCycleStatus = document.getElementById("bot-stat-cycle-status");
    const statCycleTime = document.getElementById("bot-stat-cycle-time");

    const condorId = document.getElementById("bot-condor-id");
    const tpTarget = document.getElementById("bot-tp-target");
    const tpFill = document.getElementById("bot-tp-fill");
    const legsBody = document.getElementById("bot-legs-body");
    const messageText = document.getElementById("bot-message-text");

    if (!badge || !btnToggle) return; // Not on page

    let isRunning = false;
    let botSocket = null;

    function formatCurrency(val) {
      if (val === null || val === undefined) return "$0.00";
      const num = Number(val);
      const sign = num < 0 ? "-" : "";
      return `${sign}$${Math.abs(num).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }

    function renderBotState(data) {
      if (!data) return;
      const ctrl = data.control || {};
      const port = data.portfolio || {};
      const margin = data.margin || {};
      const active = data.active_condor;

      // Update control & running state
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

      // Update Stats
      if (statEquity) statEquity.textContent = formatCurrency(port.equity);
      if (statCash) statCash.textContent = `Cash: ${formatCurrency(port.cash_balance)}`;

      if (statUnrealized) {
        const u = port.total_unrealized_pnl || 0;
        statUnrealized.textContent = (u >= 0 ? "+" : "") + formatCurrency(u);
        statUnrealized.style.color = u >= 0 ? "#3ca572" : "#ef4444";
      }
      if (statCompounded) {
        const c = port.total_compounded_profit || 0;
        statCompounded.textContent = `Đã chốt: ${(c >= 0 ? "+" : "") + formatCurrency(c)}`;
      }

      if (statMargin && marginMeter) {
        const util = margin.margin_utilization_pct || 0;
        statMargin.textContent = `${util.toFixed(1)}%`;
        marginMeter.style.width = `${Math.min(100, Math.max(0, util))}%`;
        marginMeter.className = "bot-margin-meter";
        if (margin.is_critical) marginMeter.classList.add("critical");
        else if (margin.is_warning) marginMeter.classList.add("warning");
      }

      if (statCycleStatus) statCycleStatus.textContent = ctrl.last_cycle_status || "IDLE";
      if (statCycleTime) {
        statCycleTime.textContent = ctrl.last_cycle_time ? new Date(ctrl.last_cycle_time).toLocaleTimeString() : "Chưa quét";
      }

      // Render Active Condor
      if (active && Array.isArray(active.legs) && active.legs.length > 0) {
        if (condorId) condorId.textContent = `${active.condor_id} (Credit: ${formatCurrency(active.entry_credit)})`;
        if (tpTarget) tpTarget.textContent = formatCurrency(active.target_profit_50);

        // TP Progress
        const target = active.target_profit_50 || 1;
        const currentUnrealized = active.unrealized_pnl || 0;
        const pct = Math.min(100, Math.max(0, (currentUnrealized / target) * 100));
        if (tpFill) tpFill.style.width = `${pct}%`;

        // Table Rows
        if (legsBody) {
          legsBody.textContent = ""; // clear
          active.legs.forEach((leg) => {
            const isShort = leg.side === "Sell";
            const roleClass = isShort ? "bot-role-short" : "bot-role-wing";
            const pnl = leg.unrealized_pnl || 0;
            const pnlColor = pnl >= 0 ? "#3ca572" : "#ef4444";
            const pnlStr = (pnl >= 0 ? "+" : "") + formatCurrency(pnl);

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
            tdPnl.textContent = pnlStr;
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
          td.textContent = "Không có vị thế Iron Condor nào đang chạy. Bấm \"Quét ngay\" hoặc \"Bật Bot\" để tự động tìm cơ hội.";
          tr.appendChild(td);
          legsBody.appendChild(tr);
        }
      }

      if (messageText && ctrl.last_action_message) {
        messageText.textContent = ctrl.last_action_message;
      }
    }

    async function sendControl(action, extra = {}) {
      try {
        if (messageText) messageText.textContent = `Đang gửi lệnh ${action}...`;
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
      }
    }

    // Connect WebSocket
    function connectBotStream() {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const url = `${protocol}//${window.location.host}/api/v1/bot/stream`;
      botSocket = new WebSocket(url);

      botSocket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          renderBotState(data);
        } catch (e) {
          console.warn("Invalid bot stream payload", e);
        }
      };

      botSocket.onclose = () => {
        setTimeout(connectBotStream, 3000); // Auto reconnect
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
      .then(renderBotState)
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
