// ──────────────────────────────────────────────────────────────
//  nifty-ai dashboard
// ──────────────────────────────────────────────────────────────

const API = {
  market: (instrument, expiry) => `/api/market?instrument=${encodeURIComponent(instrument)}${expiry ? `&expiry=${encodeURIComponent(expiry)}` : ""}`,
  scenario: (instrument, expiry) => `/api/scenario?instrument=${encodeURIComponent(instrument)}${expiry ? `&expiry=${encodeURIComponent(expiry)}` : ""}`,
  expiries: (instrument) => `/api/expiries?instrument=${encodeURIComponent(instrument)}`,
  events: (instrument) => `/api/events?instrument=${encodeURIComponent(instrument)}&days=30`,
  chat: "/api/chat",
  clear: "/api/session/clear",
  positions: "/api/positions",
  tradesLog: "/api/trades/log",
  trades: "/api/trades",
  intradayStatus: (instrument, expiry) => `/api/intraday/status?instrument=${encodeURIComponent(instrument)}${expiry ? `&expiry=${encodeURIComponent(expiry)}` : ""}`,
};

const state = {
  instrument: "NIFTY",
  expiry: null,
  context: null,
  prevSpot: null,
  sessionId: crypto.randomUUID(),
  mode: "both",
};

// ──────────────────────────────────────────────────────────────
//  formatting helpers
// ──────────────────────────────────────────────────────────────

const fmt = {
  price(n, decimals = 2) {
    if (n === null || n === undefined || Number.isNaN(n)) return "—";
    return Number(n).toLocaleString("en-IN", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
  },
  int(n) {
    if (n === null || n === undefined || Number.isNaN(n)) return "—";
    return Number(n).toLocaleString("en-IN");
  },
  pct(n, decimals = 1) {
    if (n === null || n === undefined || Number.isNaN(n)) return "—";
    return `${Number(n).toFixed(decimals)}%`;
  },
  greek(n) {
    if (n === null || n === undefined || Number.isNaN(n)) return "—";
    return Number(n).toFixed(2);
  },
  rupees(n) {
    if (n === null || n === undefined || Number.isNaN(n)) return "₹0";
    const sign = n < 0 ? "−" : "";
    return `${sign}₹${Math.abs(n).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
  },
  time() {
    return new Date().toLocaleTimeString("en-IN", { hour12: false });
  },
};

// ──────────────────────────────────────────────────────────────
//  interpretation helpers
// ──────────────────────────────────────────────────────────────

function ivRankInterp(rank) {
  if (rank == null) return { text: "—", cls: "" };
  if (rank >= 70) return { text: "High — favor selling premium", cls: "warn" };
  if (rank <= 30) return { text: "Low — favor buying premium", cls: "bull" };
  return { text: "Mid — directional plays preferred", cls: "" };
}

function pcrInterp(pcr) {
  if (pcr == null) return { text: "—", cls: "" };
  if (pcr >= 1.3) return { text: "Bullish — heavy put writing", cls: "bull" };
  if (pcr <= 0.7) return { text: "Bearish — heavy call writing", cls: "bear" };
  return { text: "Neutral — balanced positioning", cls: "" };
}

function trendInterp(trend) {
  if (!trend) return { text: "—", cls: "" };
  if (trend === "bullish") return { text: "Price > EMA20 > EMA50", cls: "bull" };
  if (trend === "bearish") return { text: "Price < EMA20 < EMA50", cls: "bear" };
  return { text: "EMAs intertwined", cls: "warn" };
}

// ──────────────────────────────────────────────────────────────
//  top bar
// ──────────────────────────────────────────────────────────────

function renderTopbar(ctx) {
  document.getElementById("topbar-spot").textContent = fmt.price(ctx.spot);
  document.getElementById("topbar-atm").textContent = fmt.int(ctx.atm_strike);
  document.getElementById("topbar-dte").textContent = ctx.days_to_expiry ?? "—";
  document.getElementById("topbar-vix").textContent = fmt.price(ctx.india_vix);
  document.getElementById("topbar-refreshed").textContent = fmt.time();

  const changeEl = document.getElementById("topbar-change");
  if (state.prevSpot != null && ctx.spot != null) {
    const diff = ctx.spot - state.prevSpot;
    const pct = (diff / state.prevSpot) * 100;
    const cls = diff > 0 ? "up" : diff < 0 ? "down" : "flat";
    changeEl.className = `stat-change ${cls}`;
    changeEl.textContent = `${diff >= 0 ? "+" : ""}${fmt.price(diff)} (${fmt.pct(pct, 2)})`;
  } else {
    changeEl.textContent = "";
  }
  state.prevSpot = ctx.spot;

  const id = ctx.intraday;
  document.getElementById("topbar-vwap").textContent = id ? fmt.price(id.vwap) : "—";
  const intradayEl = document.getElementById("topbar-intraday");
  if (id) {
    const trend = id.intraday_trend;
    const cls = trend === "bullish" ? "bull" : trend === "bearish" ? "bear" : "flat";
    const arrow = trend === "bullish" ? "▲" : trend === "bearish" ? "▼" : "→";
    intradayEl.textContent = `${arrow} ${trend.charAt(0).toUpperCase() + trend.slice(1)}`;
    intradayEl.className = `stat-value ${cls}`;
  } else {
    intradayEl.textContent = "—";
    intradayEl.className = "stat-value";
  }
}

// ──────────────────────────────────────────────────────────────
//  intraday status indicator
// ──────────────────────────────────────────────────────────────

function renderIntradayStatus(intraday) {
  const btn   = document.getElementById("intraday-status-btn");
  const label = document.getElementById("intraday-status-label");
  if (!btn || !label) return;
  const setup = intraday?.active_setup;
  if (setup) {
    btn.classList.add("active");
    label.textContent = setup.replace(/_/g, " ");
  } else {
    btn.classList.remove("active");
    label.textContent = "no setup";
  }
}

// ──────────────────────────────────────────────────────────────
//  left panel — signals, technicals, positions, capital
// ──────────────────────────────────────────────────────────────

function renderSignals(ctx) {
  const t = ctx.technicals || {};

  const iv = ivRankInterp(t.iv_rank);
  document.getElementById("sig-iv").textContent = t.iv_rank != null ? fmt.pct(t.iv_rank) : "—";
  const ivInterp = document.getElementById("sig-iv-interp");
  ivInterp.textContent = iv.text;
  ivInterp.className = `signal-interp ${iv.cls}`;

  const pcr = pcrInterp(ctx.pcr);
  document.getElementById("sig-pcr").textContent = ctx.pcr != null ? ctx.pcr.toFixed(2) : "—";
  const pcrEl = document.getElementById("sig-pcr-interp");
  pcrEl.textContent = pcr.text;
  pcrEl.className = `signal-interp ${pcr.cls}`;

  const trend = trendInterp(ctx.trend);
  const trendVal = document.getElementById("sig-trend");
  trendVal.textContent = ctx.trend ? ctx.trend.charAt(0).toUpperCase() + ctx.trend.slice(1) : "—";
  trendVal.className = `signal-value ${trend.cls}`;
  const trendInterpEl = document.getElementById("sig-trend-interp");
  trendInterpEl.textContent = trend.text;
  trendInterpEl.className = `signal-interp ${trend.cls}`;
}

function renderTechnicals(ctx) {
  const t = ctx.technicals || {};
  document.getElementById("t-ema20").textContent = fmt.price(t.ema_20);
  document.getElementById("t-ema50").textContent = fmt.price(t.ema_50);

  const sup1 = t.support;
  const sup2 = sup1 != null ? sup1 * 0.985 : null;
  const res1 = t.resistance;
  const res2 = res1 != null ? res1 * 1.015 : null;
  document.getElementById("t-sup1").textContent = fmt.price(sup1);
  document.getElementById("t-sup2").textContent = fmt.price(sup2);
  document.getElementById("t-res1").textContent = fmt.price(res1);
  document.getElementById("t-res2").textContent = fmt.price(res2);

  document.getElementById("t-maxpain").textContent = ctx.max_pain != null ? fmt.int(ctx.max_pain) : "—";

  const ce = (ctx.oi_walls?.ce || []).map(w => `${fmt.int(w.strike)} (${fmt.int(w.oi)})`).join(", ") || "—";
  const pe = (ctx.oi_walls?.pe || []).map(w => `${fmt.int(w.strike)} (${fmt.int(w.oi)})`).join(", ") || "—";
  document.getElementById("t-ce-walls").textContent = ce;
  document.getElementById("t-pe-walls").textContent = pe;
}

function renderPositions(positions) {
  const container = document.getElementById("positions-list");
  if (!positions || positions.length === 0) {
    container.innerHTML = '<div class="positions-empty">No open positions</div>';
    return;
  }
  container.innerHTML = positions.map(p => {
    const pnl = Number(p.pnl ?? p.m2m ?? 0);
    const pnlCls = pnl > 0 ? "up" : pnl < 0 ? "down" : "flat";
    const avg = Number(p.average_price ?? p.entry_price ?? 0);
    const ltp = Number(p.last_price ?? 0);
    const pnlPct = avg > 0 ? ((ltp - avg) / avg) * 100 * Math.sign(p.quantity || 1) : 0;
    const g = p.greeks || {};
    return `
      <div class="position">
        <div class="position-header">
          <span class="position-name">${p.tradingsymbol || p.symbol || "—"}</span>
          <span class="position-pnl ${pnlCls}">${fmt.rupees(pnl)}</span>
        </div>
        <div class="position-meta">
          <span>Qty ${p.quantity ?? 0}</span>
          <span>Avg ${fmt.price(avg)}</span>
          <span>LTP ${fmt.price(ltp)}</span>
          <span class="${pnlCls}">${fmt.pct(pnlPct)}</span>
        </div>
        <div class="position-greeks">
          <span>Δ <b>${fmt.greek(g.delta)}</b></span>
          <span>Γ <b>${fmt.greek(g.gamma)}</b></span>
          <span>Θ <b>${fmt.greek(g.theta)}</b></span>
          <span>ν <b>${fmt.greek(g.vega)}</b></span>
        </div>
      </div>
    `;
  }).join("");
}

function renderCapital(positions) {
  const deployed = (positions || []).reduce((sum, p) => {
    const avg = Number(p.average_price ?? 0);
    const qty = Math.abs(Number(p.quantity ?? 0));
    return sum + avg * qty;
  }, 0);
  const pnl = (positions || []).reduce((sum, p) => sum + Number(p.pnl ?? p.m2m ?? 0), 0);
  document.getElementById("cap-deployed").textContent = fmt.rupees(deployed);
  const pnlEl = document.getElementById("cap-pnl");
  pnlEl.textContent = fmt.rupees(pnl);
  pnlEl.className = pnl > 0 ? "up" : pnl < 0 ? "down" : "flat";
}

// ──────────────────────────────────────────────────────────────
//  option chain
// ──────────────────────────────────────────────────────────────

function renderChain(ctx) {
  const body = document.getElementById("chain-body");
  const strikes = ctx.strikes || [];
  if (strikes.length === 0) {
    body.innerHTML = '<tr><td colspan="13" class="chain-empty">No chain data available</td></tr>';
    return;
  }
  const atm = ctx.atm_strike;
  const spot = ctx.spot;

  body.innerHTML = strikes.map(s => {
    const ce = s.CE || {};
    const pe = s.PE || {};
    const isAtm = s.strike === atm;
    const ceItm = spot != null && s.strike < spot ? "itm" : "";
    const peItm = spot != null && s.strike > spot ? "itm" : "";
    return `
      <tr class="${isAtm ? "atm" : ""}" data-strike="${s.strike}">
        <td class="${ceItm}">${fmt.int(ce.oi)}</td>
        <td class="${ceItm}">${fmt.int(ce.volume)}</td>
        <td class="${ceItm}">${fmt.greek(ce.delta)}</td>
        <td class="${ceItm}">${fmt.greek(ce.theta)}</td>
        <td class="${ceItm}">${ce.iv != null ? fmt.pct(ce.iv * 100) : "—"}</td>
        <td class="${ceItm}">${fmt.price(ce.ltp)}</td>
        <td class="strike-cell">${fmt.int(s.strike)}</td>
        <td class="${peItm}">${fmt.price(pe.ltp)}</td>
        <td class="${peItm}">${pe.iv != null ? fmt.pct(pe.iv * 100) : "—"}</td>
        <td class="${peItm}">${fmt.greek(pe.delta)}</td>
        <td class="${peItm}">${fmt.greek(pe.theta)}</td>
        <td class="${peItm}">${fmt.int(pe.volume)}</td>
        <td class="${peItm}">${fmt.int(pe.oi)}</td>
      </tr>
    `;
  }).join("");

  body.querySelectorAll("tr").forEach(row => {
    row.addEventListener("click", () => {
      const strike = row.dataset.strike;
      if (!strike) return;
      const input = document.getElementById("chat-input");
      const note = `What do you think about the ${fmt.int(parseFloat(strike))} strike for ${state.instrument}?`;
      input.value = note;
      input.focus();
    });
  });

  // Scroll ATM into view
  const atmRow = body.querySelector("tr.atm");
  if (atmRow) atmRow.scrollIntoView({ block: "center", behavior: "instant" });
}

// ──────────────────────────────────────────────────────────────
//  strategy builder — scenario-driven cards
// ──────────────────────────────────────────────────────────────

const SCENARIO_LABELS = {
  expiry_day:        "Expiry Day — gamma risk is extreme",
  high_vix:          "High VIX — position sizing reduced",
  high_iv_bearish:   "High IV Bearish — favor premium selling",
  high_iv_bullish:   "High IV Bullish — sell puts with trend",
  low_iv_bullish:    "Low IV Bullish — buy cheap calls",
  low_iv_bearish:    "Low IV Bearish — buy cheap puts",
  long_volatility:   "Long Volatility — cheap options, bet on a move",
  neutral_rangebound:"Neutral / Range-bound — collect theta",
};

async function renderBuilder(ctx) {
  const container = document.getElementById("builder-grid");

  let scenarioData = null;
  try {
    scenarioData = await fetchJSON(API.scenario(state.instrument, state.expiry));
  } catch (err) {
    container.innerHTML = `<div class="builder-empty">Could not load scenario: ${err.message}</div>`;
    return;
  }

  const scenario = scenarioData.scenario || ctx.scenario || "neutral_rangebound";
  const label = SCENARIO_LABELS[scenario] || scenario;
  const primary = scenarioData.primary_strategy || "";
  const reasoning = scenarioData.reasoning || "";
  const alternatives = scenarioData.alternatives || [];

  function buildCard(name, isPrimary) {
    const msg = `Build the ${name} trade for ${state.instrument} right now using current market data. Follow the output format exactly.`;
    return `
      <div class="strategy-card${isPrimary ? " strategy-card-primary" : ""}">
        <div class="strategy-header">
          <span class="strategy-name">${name}</span>
          ${isPrimary ? '<span class="strategy-badge">Primary</span>' : '<span class="strategy-badge strategy-badge-alt">Alternative</span>'}
        </div>
        ${isPrimary ? `<div class="strategy-rationale">${reasoning}</div>` : ""}
        <button class="btn btn-build" data-msg="${msg.replace(/"/g, "&quot;")}">Build this trade</button>
      </div>
    `;
  }

  container.innerHTML = `
    <div class="scenario-banner">
      <span class="scenario-label">Active scenario:</span>
      <span class="scenario-name">${label}</span>
    </div>
    ${buildCard(primary, true)}
    ${alternatives.map(alt => buildCard(alt, false)).join("")}
  `;

  container.querySelectorAll(".btn-build").forEach(btn => {
    btn.addEventListener("click", () => {
      sendChatMessage(btn.dataset.msg);
    });
  });
}

// ──────────────────────────────────────────────────────────────
//  events tab
// ──────────────────────────────────────────────────────────────

const SOURCE_LABEL = {
  kite_expiry: "Kite",
  nse_holiday: "NSE",
  nse_events:  "NSE",
};

function renderEvents(events) {
  const container = document.getElementById("events-list");
  if (!events || events.length === 0) {
    container.innerHTML = '<div class="events-empty">No upcoming events in the next 30 days.</div>';
    return;
  }

  const items = events.map(ev => {
    const impactCls = ev.impact === "HIGH" ? "event-high" : "event-medium";
    const dayCls    = ev.days_away === 0 ? "urgent"
                    : ev.days_away <= 3  ? "soon" : "";
    const dayLabel  = ev.days_away === 0 ? "Today"
                    : ev.days_away === 1 ? "Tomorrow"
                    : `${ev.days_away}d away`;
    const src       = SOURCE_LABEL[ev.source] || ev.source;
    return `
      <div class="event-item ${impactCls}">
        <div class="event-dot"></div>
        <div class="event-content">
          <div class="event-header-row">
            <span class="event-name">${ev.name}</span>
            <span class="event-badge">${ev.impact}</span>
          </div>
          <div class="event-meta-row">
            <span class="event-date">${ev.date_str}</span>
            <span class="event-dot-sep">·</span>
            <span class="event-days ${dayCls}">${dayLabel}</span>
            <span class="event-source-chip">${src}</span>
          </div>
          ${ev.notes ? `<div class="event-notes">${ev.notes}</div>` : ""}
        </div>
      </div>`;
  }).join("");

  container.innerHTML = `<div class="events-timeline">${items}</div>`;
}

// ──────────────────────────────────────────────────────────────
//  expiry selector
// ──────────────────────────────────────────────────────────────

function renderExpiryBar(expiries) {
  const bar = document.getElementById("chain-expiry-bar");
  if (!expiries || expiries.length === 0) {
    bar.innerHTML = "";
    return;
  }
  bar.innerHTML = expiries.map(e => {
    const isActive = state.expiry === e.date || (state.expiry === null && expiries[0].date === e.date);
    return `<button class="expiry-pill${isActive ? " active" : ""}" data-expiry="${e.date}">
      ${e.label}<span class="expiry-type-badge">${e.type}</span>
    </button>`;
  }).join("");

  bar.querySelectorAll(".expiry-pill").forEach((pill, idx) => {
    pill.addEventListener("click", () => {
      selectExpiry(idx === 0 ? null : pill.dataset.expiry);
    });
  });
}

async function selectExpiry(expiryDate) {
  if (state.expiry === expiryDate) return;
  state.expiry = expiryDate;

  {
    const bar = document.getElementById("chain-expiry-bar");
    bar.querySelectorAll(".expiry-pill").forEach(p => {
      const match = expiryDate ? p.dataset.expiry === expiryDate : p === bar.querySelector(".expiry-pill");
      p.classList.toggle("active", match);
    });
  }

  try {
    const ctx = await fetchJSON(API.market(state.instrument, state.expiry));
    state.context = ctx;
    renderTopbar(ctx);
    renderSignals(ctx);
    renderTechnicals(ctx);
    renderChain(ctx);
    await renderBuilder(ctx);
  } catch (err) {
    console.error("selectExpiry failed:", err);
  }
}

// ──────────────────────────────────────────────────────────────
//  fetch + render orchestration
// ──────────────────────────────────────────────────────────────

async function fetchJSON(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}${text ? `: ${text}` : ""}`);
  }
  return res.json();
}

async function refreshAll() {
  try {
    const [ctx, positions, events] = await Promise.all([
      fetchJSON(API.market(state.instrument, state.expiry)),
      fetchJSON(API.positions).catch(() => []),
      fetchJSON(API.events(state.instrument)).catch(() => []),
    ]);
    state.context = ctx;
    renderTopbar(ctx);
    renderIntradayStatus(ctx.intraday);
    renderSignals(ctx);
    renderTechnicals(ctx);
    renderChain(ctx);
    await renderBuilder(ctx);
    renderPositions(positions);
    renderCapital(positions);
    renderExpiryBar(ctx.expiries || []);
    renderEvents(events);
  } catch (err) {
    console.error("Failed to refresh:", err);
    alert(`Failed to load market data: ${err.message}`);
  }
}

// ──────────────────────────────────────────────────────────────
//  chat
// ──────────────────────────────────────────────────────────────

function appendChat(role, content, { pending = false } = {}) {
  const el = document.createElement("div");
  el.className = `chat-msg chat-msg-${role}${pending ? " chat-msg-pending" : ""}`;
  el.innerHTML = `<div class="chat-msg-body"></div>`;
  el.querySelector(".chat-msg-body").textContent = content;
  const messages = document.getElementById("chat-messages");
  messages.appendChild(el);
  messages.scrollTop = messages.scrollHeight;
  return el;
}

async function sendChatMessage(text) {
  if (!text.trim()) return;
  let message = text;
  if (state.mode === "intraday") message += " (intraday only)";
  else if (state.mode === "positional") message += " (positional only)";
  appendChat("user", text);
  const pending = appendChat("assistant", "Thinking…", { pending: true });
  try {
    const data = await fetchJSON(API.chat, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: state.sessionId,
        message,
        instrument: state.instrument,
        expiry: state.expiry,
      }),
    });
    pending.classList.remove("chat-msg-pending");
    pending.querySelector(".chat-msg-body").textContent = data.response;
  } catch (err) {
    pending.classList.remove("chat-msg-pending");
    pending.querySelector(".chat-msg-body").textContent = `Error: ${err.message}`;
  }
}

async function clearChat() {
  try {
    await fetchJSON(API.clear, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId }),
    });
  } catch (err) {
    console.error("Failed to clear session:", err);
  }
  document.getElementById("chat-messages").innerHTML = `
    <div class="chat-msg chat-msg-assistant">
      <div class="chat-msg-body">Cleared. What's next?</div>
    </div>
  `;
}

// ──────────────────────────────────────────────────────────────
//  trade log modal
// ──────────────────────────────────────────────────────────────

function openTradeModal() {
  document.getElementById("trade-modal").classList.remove("hidden");
  document.querySelector("#trade-form [name=instrument]").value = state.instrument;
}

function closeTradeModal() {
  document.getElementById("trade-modal").classList.add("hidden");
  document.getElementById("trade-form").reset();
}

async function submitTrade(event) {
  event.preventDefault();
  const form = event.target;
  const data = new FormData(form);
  const legs = (data.get("legs") || "").toString().split("\n").map(l => l.trim()).filter(Boolean);
  try {
    await fetchJSON(API.tradesLog, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        instrument: data.get("instrument"),
        strategy: data.get("strategy"),
        legs,
        notes: data.get("notes") || null,
      }),
    });
    closeTradeModal();
    appendChat("assistant", "Trade logged.");
  } catch (err) {
    alert(`Failed to log trade: ${err.message}`);
  }
}

// ──────────────────────────────────────────────────────────────
//  wiring
// ──────────────────────────────────────────────────────────────

function wireUp() {
  document.querySelectorAll("#instrument-toggle button").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#instrument-toggle button").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.instrument = btn.dataset.instrument;
      state.expiry = null;
      state.prevSpot = null;
      refreshAll();
    });
  });

  document.querySelectorAll("#mode-toggle button").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#mode-toggle button").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.mode = btn.dataset.mode;
      refreshAll();
    });
  });

  document.getElementById("intraday-status-btn").addEventListener("click", () => {
    sendChatMessage("What intraday setup is active and should I take it?");
  });

  document.getElementById("refresh-btn").addEventListener("click", refreshAll);

  document.querySelectorAll("#tabs .tab").forEach(tab => {
    tab.addEventListener("click", () => {
      document.querySelectorAll("#tabs .tab").forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));
      tab.classList.add("active");
      document.getElementById(`pane-${tab.dataset.tab}`).classList.add("active");
    });
  });

  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  form.addEventListener("submit", e => {
    e.preventDefault();
    const text = input.value;
    input.value = "";
    sendChatMessage(text);
  });
  input.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });
  document.getElementById("chat-clear-btn").addEventListener("click", clearChat);

  document.getElementById("log-trade-btn").addEventListener("click", openTradeModal);
  document.getElementById("trade-modal-close").addEventListener("click", closeTradeModal);
  document.getElementById("trade-cancel-btn").addEventListener("click", closeTradeModal);
  document.getElementById("trade-form").addEventListener("submit", submitTrade);
  document.getElementById("trade-modal").addEventListener("click", e => {
    if (e.target.id === "trade-modal") closeTradeModal();
  });
}

document.addEventListener("DOMContentLoaded", () => {
  wireUp();
  refreshAll();
  setInterval(async () => {
    try {
      const intraday = await fetchJSON(API.intradayStatus(state.instrument, state.expiry));
      renderIntradayStatus(intraday);
    } catch (err) {
      console.error("Intraday status poll failed:", err);
    }
  }, 5 * 60 * 1000);
});
