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

  function edgePercent(item) {
    const edge = finiteNumber(firstDefined(item?.edge_pct, item?.iv_edge));
    return edge === null ? null : edge;
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

  function normalizeMarketCard(value, fallbackAsset, opportunityItems) {
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
    const opportunityCount = readCount(object, [
      "opportunity_count",
      "opportunities_count",
      "qualified_count",
      "signal_count",
      "signals",
      "opportunities",
    ]);
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
      opportunityCount: opportunityCount === null ? opportunityItems.length : opportunityCount,
      quoteTimestamp,
      quoteSource,
      opportunityItems,
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
    const grouped = new Map();
    opportunities.forEach((item) => {
      const asset = String(firstDefined(item?.asset, "—"));
      const current = grouped.get(asset) || [];
      current.push(item);
      grouped.set(asset, current);
    });
    const cardRecords = recordsFrom(rawCards);
    const cardAssets = cardRecords.map((item) => cardAsset(item));
    const assets = uniqueStrings([...selectedAssets, ...cardAssets, ...grouped.keys()]);
    const markets = assets.map((asset) => {
      const card = cardRecords.find((item) => cardAsset(item) === asset);
      return normalizeMarketCard(card || { asset }, asset, grouped.get(asset) || []);
    });
    const summary = record(raw.summary) || {};
    const contractCount = firstDefined(
      readCount(raw, ["contract_count", "contracts_count", "total_contracts", "option_contract_count", "contracts"]),
      readCount(summary, ["contract_count", "contracts_count", "total_contracts", "contracts"]),
      markets.reduce((sum, market) => sum + (market.contractCount || 0), 0) || null,
    );
    const opportunityCount = firstDefined(
      readCount(raw, ["opportunity_count", "opportunities_count", "qualified_count", "signal_count"]),
      readCount(summary, ["opportunity_count", "opportunities_count", "qualified_count", "signal_count"]),
      opportunities.length,
    );
    return {
      opportunities,
      markets,
      spot: spotFromDesk(raw, markets, opportunities, selectedAssets),
      contractCount,
      opportunityCount,
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
    const strategyLabel = options.strategyLabel || ((strategy) => String(strategy || "—"));
    const opportunitySymbol = options.opportunitySymbol || ((item) => String(item?.symbol || "Mã chưa có"));
    const onOpportunityDetail = options.onOpportunityDetail || (() => {});
    const onLog = options.onLog || (() => {});
    const serviceStatus = elements.serviceStatus;
    let socket = null;
    let reconnectTimer = null;
    let request = null;
    let wanted = false;
    let updateCount = 0;
    let state = "idle";

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
        if (market.opportunityCount !== null) detailParts.push(`${countLabel(market.opportunityCount)} signal${market.opportunityCount === 1 ? "" : "s"}`);
        if (!detailParts.length && market.opportunityItems.length) detailParts.push(strategyLabel(market.opportunityItems[0].strategy));
        detail.textContent = detailParts.join(" · ") || "Chưa có market data";
        card.append(heading, spot, detail);
        target.appendChild(card);
      });
    }

    function renderSignalChart(opportunities) {
      const target = elements.signalChart;
      if (!target) return;
      target.replaceChildren();
      const ranked = opportunities
        .map((item) => ({ item, value: edgePercent(item) }))
        .filter((entry) => entry.value !== null)
        .sort((left, right) => right.value - left.value)
        .slice(0, 8);
      if (!ranked.length) {
        const empty = document.createElement("div");
        empty.className = "signal-chart-empty";
        empty.textContent = opportunities.length ? "Chưa có model edge để vẽ." : "Không có cơ hội đạt điều kiện hiện tại.";
        target.appendChild(empty);
        if (elements.liveSignalStatus) elements.liveSignalStatus.textContent = opportunities.length ? "Có signal · thiếu edge" : "Không có signal";
        return;
      }
      const maxValue = Math.max(...ranked.map((entry) => Math.abs(entry.value)), 0.01);
      ranked.forEach(({ item, value }, index) => {
        const column = document.createElement("div");
        column.className = "signal-column";
        const valueLabel = document.createElement("span");
        valueLabel.className = "signal-value";
        valueLabel.textContent = `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)}%`;
        const track = document.createElement("div");
        track.className = "signal-track";
        const bar = document.createElement("span");
        bar.className = value >= 0 ? "signal-bar" : "signal-bar signal-bar-negative";
        bar.style.height = `${Math.max(12, Math.abs(value) / maxValue * 100)}%`;
        track.appendChild(bar);
        const label = document.createElement("span");
        label.className = "signal-label";
        label.textContent = `${index + 1} · ${item.asset || "—"}`;
        column.append(valueLabel, track, label);
        target.appendChild(column);
      });
      if (elements.liveSignalStatus) elements.liveSignalStatus.textContent = `${opportunities.length} signal${opportunities.length > 1 ? "s" : ""} · top ${ranked.length}`;
    }

    function renderOpportunityBoard(opportunities) {
      const target = elements.liveOpportunityBody;
      if (!target) return;
      target.replaceChildren();
      const ranked = [...opportunities]
        .sort((left, right) => (edgePercent(right) || 0) - (edgePercent(left) || 0))
        .slice(0, 8);
      if (!ranked.length) {
        const row = document.createElement("tr");
        const empty = document.createElement("td");
        empty.className = "live-board-empty";
        empty.colSpan = 6;
        empty.textContent = "Snapshot đã nhận nhưng chưa có signal phù hợp.";
        row.appendChild(empty);
        target.appendChild(row);
        return;
      }
      ranked.forEach((item) => {
        const row = document.createElement("tr");
        const instrument = document.createElement("td");
        instrument.className = "live-board-instrument";
        const asset = document.createElement("strong");
        asset.textContent = item.asset || "—";
        const symbol = document.createElement("span");
        symbol.textContent = opportunitySymbol(item);
        instrument.append(asset, symbol);
        row.appendChild(instrument);
        appendCell(row, strategyLabel(item.strategy));
        const edge = edgePercent(item);
        appendCell(row, edge === null ? "—" : `${edge >= 0 ? "+" : ""}${(edge * 100).toFixed(2)}%`, edge === null || edge < 0 ? "negative" : "positive");
        appendCell(row, Number.isFinite(Number(item.dte)) ? `${Math.round(Number(item.dte))}d` : "—");
        appendCell(row, compactNumber(firstDefined(item.estimated_entry, item.market_mid)));
        const action = document.createElement("td");
        const detailButton = document.createElement("button");
        detailButton.type = "button";
        detailButton.className = "live-board-detail";
        detailButton.textContent = "Payoff";
        detailButton.addEventListener("click", () => onOpportunityDetail(item));
        action.appendChild(detailButton);
        row.appendChild(action);
        target.appendChild(row);
      });
    }

    function renderFeed(opportunities) {
      const target = elements.liveFeed;
      if (!target) return;
      target.replaceChildren();
      const ranked = [...opportunities]
        .sort((left, right) => (edgePercent(right) || 0) - (edgePercent(left) || 0))
        .slice(0, 6);
      if (!ranked.length) {
        const empty = document.createElement("div");
        empty.className = "live-feed-empty";
        empty.textContent = "Snapshot đã nhận nhưng chưa có signal phù hợp.";
        target.appendChild(empty);
        return;
      }
      ranked.forEach((item, index) => {
        const event = document.createElement("div");
        event.className = "live-event";
        const indexLabel = document.createElement("span");
        indexLabel.className = "live-event-index";
        indexLabel.textContent = String(index + 1).padStart(2, "0");
        const copy = document.createElement("div");
        copy.className = "live-event-copy";
        const title = document.createElement("strong");
        title.textContent = `${item.asset || "—"} · ${strategyLabel(item.strategy)}`;
        const symbol = document.createElement("span");
        symbol.textContent = opportunitySymbol(item);
        copy.append(title, symbol);
        const edge = document.createElement("strong");
        const edgeValue = edgePercent(item);
        edge.className = edgeValue === null || edgeValue < 0 ? "live-event-edge negative" : "live-event-edge positive";
        edge.textContent = edgeValue === null ? "—" : `${edgeValue >= 0 ? "+" : ""}${(edgeValue * 100).toFixed(2)}%`;
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
      const first = opportunities[0];
      const edgeValues = opportunities.map(edgePercent).filter((value) => value !== null);
      const dtes = opportunities.map((item) => Number(item.dte)).filter(Number.isFinite);
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
      if (elements.liveStatOpportunities) elements.liveStatOpportunities.textContent = countLabel(model.opportunityCount);
      if (elements.liveStatOpportunitiesLabel) elements.liveStatOpportunitiesLabel.textContent = model.opportunityCount ? "Đang đạt bộ lọc" : "Không có signal phù hợp";
      if (elements.liveStatEdge) elements.liveStatEdge.textContent = edgeValues.length
        ? `${(edgeValues.reduce((sum, value) => sum + value, 0) / edgeValues.length * 100).toFixed(2)}%`
        : "—";
      if (elements.liveStatDte) elements.liveStatDte.textContent = dtes.length ? `${Math.round(Math.min(...dtes))}d` : "—";
      if (elements.liveStatContracts) elements.liveStatContracts.textContent = countLabel(model.contractCount);
      if (elements.liveStatContractsLabel) elements.liveStatContractsLabel.textContent = model.markets.length
        ? `${model.markets.length} market${model.markets.length > 1 ? "s" : ""} trong snapshot`
        : "Chưa có contract inventory";
      if (elements.liveStatRejections) elements.liveStatRejections.textContent = countLabel(model.rejectionSummary.total);
      if (elements.liveStatRejectionsLabel) elements.liveStatRejectionsLabel.textContent = model.rejectionSummary.reasons.length
        ? `${model.rejectionSummary.reasons[0].reason}`
        : "Không có rejection summary";
      renderMarketStrip(model);
      renderOpportunityBoard(opportunities);
      renderSignalChart(opportunities);
      renderFeed(opportunities);
      renderRejectionSummary(model.rejectionSummary);
      setConnectionState("live", `Live feed · ${model.opportunityCount} signal`);
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

  window.FlowSurfaceLiveDesk = Object.freeze({ createController });
})();
