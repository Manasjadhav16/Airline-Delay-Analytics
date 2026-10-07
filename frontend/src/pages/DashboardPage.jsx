import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ComposableMap, Geographies, Geography, Marker, useMapContext } from "react-simple-maps";
import {
  fetchStats,
  fetchModelComparison,
  fetchAirportMap,
  fetchDowHour,
  fetchDelayMinutes,
  fetchAirportBreakdown,
} from "../api";
import { AIRLINE_CODES, MONTH_LABELS_SHORT, DAY_LABELS_SHORT } from "../constants";
import SplitFlap from "../components/SplitFlap";
import "./DashboardPage.css";

const US_MAP_TOPOJSON_URL = "https://cdn.jsdelivr.net/npm/us-atlas@3/states-10m.json";

// Airport-level cells with fewer flights than this are shown as "too few
// flights" instead of a rate -- a handful of flights gives a noisy percentage.
const MIN_FLIGHTS = 30;

const HOURS = Array.from({ length: 24 }, (_, i) => i);
const DAYS = [1, 2, 3, 4, 5, 6, 7];
const MONTHS = Array.from({ length: 12 }, (_, i) => i + 1);

// Recharts draws SVG attributes, so read the CSS tokens once instead of
// duplicating hex values here.
function readTokens() {
  const css = getComputedStyle(document.documentElement);
  const get = (name) => css.getPropertyValue(name).trim();
  return {
    amber: get("--amber"),
    label: get("--label"),
    hairline: get("--hairline"),
    white: get("--on-primary"),
    surface: get("--canvas-night-soft"),
    font: get("--font-din"),
  };
}

function hexToRgb(hex) {
  const n = parseInt(hex.replace("#", ""), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function mix(fromHex, toHex, t) {
  const a = hexToRgb(fromHex);
  const b = hexToRgb(toHex);
  const rgb = a.map((c, i) => Math.round(c + (b[i] - c) * Math.min(1, Math.max(0, t))));
  return `rgb(${rgb.join(", ")})`;
}

// Heatmap starts just above the card surface so the quietest cells still
// read as cells, then runs to full amber.
const HEATMAP_LOW = "#261b08";

function useIsNarrow() {
  const query = "(max-width: 599px)";
  const [narrow, setNarrow] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = (e) => setNarrow(e.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);
  return narrow;
}

function formatMillions(n) {
  return `${(n / 1_000_000).toFixed(2)}M`;
}

function formatCount(n) {
  return n == null ? "–" : n.toLocaleString("en-US");
}

/**
 * Line up national and airport rows on a fixed key order. Airport values
 * below MIN_FLIGHTS are dropped (null) so they don't plot as real rates.
 */
function combine(keys, nationalRows, airportRows, labelFn) {
  const national = new Map(nationalRows.map((r) => [String(r.name), r]));
  const airport = airportRows ? new Map(airportRows.map((r) => [String(r.name), r])) : null;
  return keys.map((key) => {
    const n = national.get(String(key));
    const a = airport?.get(String(key));
    return {
      key,
      label: labelFn(key),
      national: n?.delay_pct ?? null,
      nationalFlights: n?.total_flights,
      airport: a && a.total_flights >= MIN_FLIGHTS ? a.delay_pct : null,
      airportFlights: a?.total_flights,
    };
  });
}

// A line can't draw a lone value between two gaps (e.g. ORD at 00:00, with
// 01:00-04:00 below MIN_FLIGHTS), so mark isolated points with a dot.
function isolatedDot(dataKey, color) {
  function IsolatedDot({ cx, cy, index, payload, points }) {
    const data = points ?? [];
    const prev = data[index - 1]?.payload?.[dataKey];
    const next = data[index + 1]?.payload?.[dataKey];
    if (payload?.[dataKey] == null || prev != null || next != null) return null;
    return <circle key={index} cx={cx} cy={cy} r={3} fill={color} />;
  }
  return IsolatedDot;
}

function BoardTooltip({ active, payload, seriesNames }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <div className="chart-tooltip">
      <div className="board-label">{row.tooltipLabel ?? row.label}</div>
      {payload
        .filter((p) => p.value != null)
        .map((p) => (
          <div key={p.dataKey} className="chart-tooltip-row">
            <span className="chart-swatch" style={{ background: p.color }} />
            <span>{seriesNames[p.dataKey]}</span>
            <strong>{p.value}%</strong>
            <span className="chart-tooltip-flights">
              {formatCount(row[`${p.dataKey}Flights`])} flights
            </span>
          </div>
        ))}
    </div>
  );
}

function ChartCard({ title, legend, note, height = 260, className = "", children }) {
  return (
    <figure className={`panel chart-card ${className}`}>
      <figcaption className="chart-card-head">
        <span className="board-label chart-card-title">{title}</span>
        {legend && (
          <span className="chart-legend">
            {legend.map((item) => (
              <span key={item.name} className="chart-legend-item">
                <span
                  className={`chart-swatch ${item.dashed ? "chart-swatch-dashed" : ""}`}
                  style={{ background: item.dashed ? "transparent" : item.color, borderColor: item.color }}
                />
                {item.name}
              </span>
            ))}
          </span>
        )}
      </figcaption>
      <ResponsiveContainer width="100%" height={height}>
        {children}
      </ResponsiveContainer>
      {note && <p className="chart-note">{note}</p>}
    </figure>
  );
}

function Kpi({ label, value, caption }) {
  return (
    <div className="kpi">
      <span className="board-label">{label}</span>
      <SplitFlap value={value} length={value.length} animateIn stagger={60} />
      <p className="kpi-caption">{caption}</p>
    </div>
  );
}

export default function DashboardPage() {
  const [stats, setStats] = useState({
    airline: null,
    airport: null,
    hour: null,
    dayofweek: null,
    month: null,
  });
  const [summary, setSummary] = useState(null);
  const [status, setStatus] = useState("loading"); // loading | success | error
  const [error, setError] = useState(null);

  // Model comparison and airport map are fetched independently of the
  // charts above, so a problem with either new section can't affect the
  // existing, already-verified dashboard charts.
  const [modelComparison, setModelComparison] = useState(null);
  const [modelComparisonStatus, setModelComparisonStatus] = useState("loading");
  const [airportMap, setAirportMap] = useState(null);
  const [airportMapStatus, setAirportMapStatus] = useState("loading");

  // Dashboard-only aggregates from src/aggregate_dashboard_v2.py, also
  // independent so a missing file only blanks its own panel.
  const [dowHour, setDowHour] = useState(null);
  const [dowHourStatus, setDowHourStatus] = useState("loading");
  const [delayMinutes, setDelayMinutes] = useState(null);
  const [delayMinutesStatus, setDelayMinutesStatus] = useState("loading");

  const [selectedAirport, setSelectedAirport] = useState(null);
  const [breakdown, setBreakdown] = useState({ status: "idle", data: null, error: null });

  const tokens = useMemo(readTokens, []);
  const narrow = useIsNarrow();

  useEffect(() => {
    fetchModelComparison()
      .then((data) => {
        setModelComparison(data);
        setModelComparisonStatus("success");
      })
      .catch(() => setModelComparisonStatus("error"));

    fetchAirportMap()
      .then((data) => {
        setAirportMap(data);
        setAirportMapStatus("success");
      })
      .catch(() => setAirportMapStatus("error"));

    fetchDowHour()
      .then((data) => {
        setDowHour(data);
        setDowHourStatus("success");
      })
      .catch(() => setDowHourStatus("error"));

    fetchDelayMinutes()
      .then((data) => {
        setDelayMinutes(data);
        setDelayMinutesStatus("success");
      })
      .catch(() => setDelayMinutesStatus("error"));
  }, []);

  useEffect(() => {
    const categories = ["airline", "airport", "hour", "dayofweek", "month"];
    Promise.all(categories.map((c) => fetchStats(c)))
      .then(([airline, airport, hour, dayofweek, month]) => {
        const airlineSorted = [...airline].sort((a, b) => b.delay_pct - a.delay_pct);
        const airportSorted = [...airport].sort((a, b) => b.delay_pct - a.delay_pct);

        const totalFlights = airline.reduce((sum, a) => sum + a.total_flights, 0);
        const totalDelayed = airline.reduce((sum, a) => sum + a.total_delayed, 0);
        const overallDelayPct = (100 * totalDelayed) / totalFlights;

        setSummary({
          totalFlights,
          overallDelayPct,
          worstAirline: airlineSorted[0],
          worstAirport: airportSorted[0],
          airportCount: airport.length,
        });

        setStats({
          airline: airlineSorted,
          airport: [...airport]
            .sort((a, b) => b.total_flights - a.total_flights)
            .slice(0, 15),
          hour: [...hour].sort((a, b) => a.name - b.name),
          dayofweek: [...dayofweek]
            .sort((a, b) => a.name - b.name)
            .map((d) => ({ ...d, label: DAY_LABELS_SHORT[d.name] })),
          month: [...month]
            .sort((a, b) => a.name - b.name)
            .map((m) => ({ ...m, label: MONTH_LABELS_SHORT[m.name] })),
        });
        setStatus("success");
      })
      .catch((err) => {
        setError(err.message);
        setStatus("error");
      });
  }, []);

  useEffect(() => {
    if (!selectedAirport) {
      setBreakdown({ status: "idle", data: null, error: null });
      return undefined;
    }
    let cancelled = false;
    setBreakdown((prev) => ({ ...prev, status: "loading", error: null }));
    fetchAirportBreakdown(selectedAirport)
      .then((data) => {
        if (!cancelled) setBreakdown({ status: "success", data, error: null });
      })
      .catch((err) => {
        if (!cancelled) setBreakdown({ status: "error", data: null, error: err.message });
      });
    return () => {
      cancelled = true;
    };
  }, [selectedAirport]);

  function toggleAirport(code) {
    setSelectedAirport((current) => (current === code ? null : code));
  }

  if (status === "loading") {
    return (
      <div className="dash-page">
        <div className="page-inner">
          <p className="board-eyebrow">Ops briefing</p>
          <h1 className="board-title">Arrivals</h1>
          <div className="panel dash-state" role="status">
            <SplitFlap value="LOADING" length={7} animateIn />
            <p className="lede">Fetching delay aggregates from the API.</p>
          </div>
        </div>
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="dash-page">
        <div className="page-inner">
          <p className="board-eyebrow">Ops briefing</p>
          <h1 className="board-title">Board offline</h1>
          <div className="panel dash-state" role="alert">
            <p className="lede dash-error">
              Could not load dashboard data from the API: {error}. Check that the backend is
              running at the configured API_BASE_URL.
            </p>
          </div>
        </div>
      </div>
    );
  }

  const airportData = breakdown.status === "success" ? breakdown.data : null;
  const focusName = airportData ? airportData.airport : null;
  const selectedMapRow = airportMap?.find((a) => a.airport === selectedAirport);

  const nationalName = "All airports";
  const seriesNames = { national: nationalName, airport: focusName ?? "" };
  const legend = focusName
    ? [
        { name: focusName, color: tokens.amber },
        { name: nationalName, color: tokens.label, dashed: true },
      ]
    : null;
  const nationalColor = focusName ? tokens.label : tokens.amber;

  const axisTick = { fill: tokens.label, fontSize: 11, fontFamily: tokens.font };
  const xAxisProps = {
    tick: axisTick,
    tickLine: false,
    axisLine: { stroke: tokens.hairline },
  };
  const yAxisProps = {
    tick: axisTick,
    tickLine: false,
    axisLine: false,
    unit: "%",
    width: 44,
  };
  const tooltipProps = {
    content: <BoardTooltip seriesNames={seriesNames} />,
    cursor: { fill: "rgba(255, 255, 255, 0.04)", stroke: tokens.hairline },
    isAnimationActive: false,
  };

  const hourData = combine(HOURS, stats.hour, airportData?.hour, (h) =>
    String(h).padStart(2, "0")
  ).map((r) => ({ ...r, tooltipLabel: `${r.label}:00 departures` }));
  const dayData = combine(DAYS, stats.dayofweek, airportData?.dayofweek, (d) =>
    DAY_LABELS_SHORT[d].toUpperCase()
  );
  const monthData = combine(MONTHS, stats.month, airportData?.month, (m) =>
    MONTH_LABELS_SHORT[m].toUpperCase()
  );

  const airlineKeys = airportData
    ? airportData.airline
        .filter((a) => a.total_flights >= MIN_FLIGHTS)
        .sort((a, b) => b.delay_pct - a.delay_pct)
        .map((a) => a.name)
    : stats.airline.map((a) => a.name);
  const airlineData = combine(airlineKeys, stats.airline, airportData?.airline, (name) =>
    narrow ? AIRLINE_CODES[name] ?? name.slice(0, 2) : name
  ).map((r) => ({ ...r, tooltipLabel: r.key }));
  const airlineChartHeight = Math.max(220, airlineData.length * (focusName ? 26 : 22) + 30);

  const onTimePct = 100 - summary.overallDelayPct;

  return (
    <div className="dash-page">
      <header className="page-inner dash-hero-head">
        <p className="board-eyebrow">Ops briefing · 2015–2016 U.S. domestic flights</p>
        <h1 className="board-title">Arrivals</h1>
        <p className="lede">
          Where and when flights arrived 15 or more minutes late, across{" "}
          {formatCount(summary.totalFlights)} completed flights. Pick an airport on the map to
          brief on it.
        </p>
      </header>

      <section className="dash-map" aria-label="Airport delay map">
        {airportMapStatus === "loading" && (
          <p className="page-inner chart-note">Loading airport map…</p>
        )}
        {airportMapStatus === "error" && (
          <p className="page-inner chart-note dash-error" role="alert">
            Could not load the airport map data.
          </p>
        )}
        {airportMapStatus === "success" && airportMap && (
          <AirportDelayMap
            airports={airportMap}
            selected={selectedAirport}
            onSelect={toggleAirport}
            tokens={tokens}
          />
        )}
      </section>

      <div className="page-inner dash-body">
        <div className="map-meta">
          <div className="map-legend">
            <span className="board-label">Delay rate</span>
            <span className="map-legend-scale">
              <span>Lower</span>
              <span
                className="map-legend-gradient"
                style={{ background: `linear-gradient(90deg, ${tokens.white}, ${tokens.amber})` }}
              />
              <span>Higher</span>
            </span>
            <span className="board-label">Dot size</span>
            <span className="map-legend-scale">Departures</span>
          </div>

          <label className="airport-filter">
            <span className="board-label">Brief on airport</span>
            <select
              value={selectedAirport ?? ""}
              onChange={(e) => setSelectedAirport(e.target.value || null)}
            >
              <option value="">All airports</option>
              {[...(airportMap ?? [])]
                .sort((a, b) => a.airport.localeCompare(b.airport))
                .map((a) => (
                  <option key={a.airport} value={a.airport}>
                    {a.airport} · {a.delay_pct}% late
                  </option>
                ))}
            </select>
          </label>
        </div>

        {selectedMapRow && (
          <p className="map-readout" aria-live="polite">
            <strong>{selectedMapRow.airport}</strong>
            {formatCount(selectedMapRow.total_flights)} departures ·{" "}
            <span className="map-readout-rate">{selectedMapRow.delay_pct}% arrived late</span>
            {" "}vs {summary.overallDelayPct.toFixed(2)}% across all airports
            <button type="button" className="text-button" onClick={() => setSelectedAirport(null)}>
              Clear
            </button>
          </p>
        )}

        <section className="kpi-row" aria-label="Network figures">
          <Kpi
            label="Flights analysed"
            value={formatMillions(summary.totalFlights)}
            caption="Completed 2015–2016 U.S. domestic flights. Cancelled and diverted flights removed."
          />
          <Kpi
            label="On time"
            value={`${onTimePct.toFixed(2)}%`}
            caption="Arrived less than 15 minutes late, the FAA definition of on time."
          />
          {delayMinutesStatus === "success" ? (
            <Kpi
              label="Avg delay when late"
              value={`${delayMinutes.mean_arrival_delay_late_min.toFixed(1)} MIN`}
              caption={`Mean arrival delay of the ${formatCount(delayMinutes.late_flights)} late flights. Median ${delayMinutes.median_arrival_delay_late_min} min.`}
            />
          ) : (
            <div className="kpi">
              <span className="board-label">Avg delay when late</span>
              <p className="kpi-caption">
                {delayMinutesStatus === "loading" ? "Loading…" : "Delay-minute data unavailable."}
              </p>
            </div>
          )}
          <Kpi
            label="Airports covered"
            value={String(summary.airportCount)}
            caption="Origins with more than 10,000 departures. Each one can be briefed from the map."
          />
        </section>

        <hr className="runway-divider" />

        <section aria-labelledby="when-heading">
          <div className="section-head">
            <div>
              <h2 id="when-heading" className="section-title">
                When delays land
              </h2>
              <p className="lede">
                Share of flights arriving 15+ minutes late, by scheduled departure.{" "}
                {focusName
                  ? `Amber is ${focusName}; grey is all airports.`
                  : "Showing all airports."}
              </p>
            </div>
            <div className="focus-board" aria-live="polite">
              <span className="board-label">Briefing</span>
              <SplitFlap value={selectedAirport ?? "ALL"} length={3} />
            </div>
          </div>

          {breakdown.status === "loading" && (
            <p className="chart-note">Loading {selectedAirport}…</p>
          )}
          {breakdown.status === "error" && (
            <p className="chart-note dash-error" role="alert">
              Could not load {selectedAirport}: {breakdown.error}
            </p>
          )}

          <DelayHeatmap
            cells={airportData ? airportData.dow_hour : dowHour}
            status={airportData ? "success" : dowHourStatus}
            scope={focusName ?? "All airports"}
            tokens={tokens}
          />

          <div className="chart-grid">
            <ChartCard title="By departure hour" legend={legend}>
              <LineChart data={hourData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <XAxis dataKey="label" {...xAxisProps} interval={narrow ? 5 : 2} />
                <YAxis {...yAxisProps} />
                <Tooltip {...tooltipProps} cursor={{ stroke: tokens.hairline }} />
                <Line
                  dataKey="national"
                  stroke={nationalColor}
                  strokeWidth={2}
                  strokeDasharray={focusName ? "4 4" : undefined}
                  dot={false}
                  activeDot={{ r: 4, stroke: tokens.surface, strokeWidth: 2 }}
                  isAnimationActive={false}
                />
                {focusName && (
                  <Line
                    dataKey="airport"
                    stroke={tokens.amber}
                    strokeWidth={2}
                    dot={isolatedDot("airport", tokens.amber)}
                    activeDot={{ r: 4, stroke: tokens.surface, strokeWidth: 2 }}
                    isAnimationActive={false}
                  />
                )}
              </LineChart>
            </ChartCard>

            <ChartCard title="By day of week" legend={legend}>
              <BarChart data={dayData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barGap={2}>
                <XAxis dataKey="label" {...xAxisProps} />
                <YAxis {...yAxisProps} />
                <Tooltip {...tooltipProps} />
                {focusName && (
                  <Bar dataKey="airport" fill={tokens.amber} radius={[4, 4, 0, 0]} maxBarSize={18} isAnimationActive={false} />
                )}
                <Bar dataKey="national" fill={nationalColor} radius={[4, 4, 0, 0]} maxBarSize={18} isAnimationActive={false} />
              </BarChart>
            </ChartCard>

            <ChartCard title="By month" legend={legend}>
              <LineChart data={monthData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <XAxis dataKey="label" {...xAxisProps} interval={narrow ? 1 : 0} />
                <YAxis {...yAxisProps} />
                <Tooltip {...tooltipProps} cursor={{ stroke: tokens.hairline }} />
                <Line
                  dataKey="national"
                  stroke={nationalColor}
                  strokeWidth={2}
                  strokeDasharray={focusName ? "4 4" : undefined}
                  dot={false}
                  activeDot={{ r: 4, stroke: tokens.surface, strokeWidth: 2 }}
                  isAnimationActive={false}
                />
                {focusName && (
                  <Line
                    dataKey="airport"
                    stroke={tokens.amber}
                    strokeWidth={2}
                    dot={isolatedDot("airport", tokens.amber)}
                    activeDot={{ r: 4, stroke: tokens.surface, strokeWidth: 2 }}
                    isAnimationActive={false}
                  />
                )}
              </LineChart>
            </ChartCard>

            <ChartCard
              title="By airline"
              legend={legend}
              height={airlineChartHeight}
              note={
                focusName
                  ? `Airlines with ${MIN_FLIGHTS}+ departures from ${focusName}.`
                  : null
              }
            >
              <BarChart
                data={airlineData}
                layout="vertical"
                margin={{ top: 0, right: 8, left: 0, bottom: 0 }}
                barGap={2}
              >
                <XAxis type="number" {...xAxisProps} unit="%" />
                <YAxis
                  type="category"
                  dataKey="label"
                  tick={axisTick}
                  tickLine={false}
                  axisLine={false}
                  width={narrow ? 32 : 168}
                  interval={0}
                />
                <Tooltip {...tooltipProps} />
                {focusName && (
                  <Bar dataKey="airport" fill={tokens.amber} radius={[0, 4, 4, 0]} maxBarSize={10} isAnimationActive={false} />
                )}
                <Bar dataKey="national" fill={nationalColor} radius={[0, 4, 4, 0]} maxBarSize={10} isAnimationActive={false} />
              </BarChart>
            </ChartCard>

            <ChartCard
              title="Busiest airports, by departures"
              className="chart-card-wide"
              height={narrow ? 15 * 22 + 40 : 260}
              note="Select a bar to brief on that airport. These are network figures and don't change with the filter."
            >
              <BarChart
                data={stats.airport}
                layout={narrow ? "vertical" : "horizontal"}
                margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
              >
                {narrow ? (
                  <>
                    <XAxis type="number" {...xAxisProps} unit="%" />
                    <YAxis type="category" dataKey="name" tick={axisTick} tickLine={false} axisLine={false} width={36} interval={0} />
                  </>
                ) : (
                  <>
                    <XAxis dataKey="name" {...xAxisProps} interval={0} />
                    <YAxis {...yAxisProps} />
                  </>
                )}
                <Tooltip
                  {...tooltipProps}
                  content={<BoardTooltip seriesNames={{ delay_pct: "Arrived late" }} />}
                />
                <Bar
                  dataKey="delay_pct"
                  radius={narrow ? [0, 4, 4, 0] : [4, 4, 0, 0]}
                  maxBarSize={narrow ? 12 : 28}
                  isAnimationActive={false}
                >
                  {stats.airport.map((row) => (
                    <Cell
                      key={row.name}
                      cursor="pointer"
                      fill={!selectedAirport || row.name === selectedAirport ? tokens.amber : tokens.label}
                      onClick={() => toggleAirport(row.name)}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ChartCard>
          </div>
        </section>

        <hr className="runway-divider" />

        <section aria-labelledby="model-heading">
          <h2 id="model-heading" className="section-title">
            Model comparison
          </h2>
          <p className="lede">
            Logistic Regression vs Decision Tree vs Random Forest, each at its own best F1
            threshold for the delayed class (from src/model_v2.py). Trained on all airports, so
            the airport filter doesn&apos;t apply here.
          </p>
          {modelComparisonStatus === "loading" && <p className="chart-note">Loading model comparison…</p>}
          {modelComparisonStatus === "error" && (
            <p className="chart-note dash-error" role="alert">
              Could not load model comparison data.
            </p>
          )}
          {modelComparisonStatus === "success" && modelComparison && (
            <ModelTable comparison={modelComparison} />
          )}
        </section>
      </div>
    </div>
  );
}

// geoAlbersUsa (the projection ComposableMap uses below) has insets for
// Alaska and Hawaii but not for Puerto Rico or other Caribbean/Pacific
// territories -- projecting those coordinates returns null and crashes
// react-simple-maps' <Marker>. Filter them out before rendering rather than
// showing a broken map.
function isProjectableUsCoordinate(lat, lon) {
  return !(lat < 25 && lon > -100);
}

function AirportDelayMap({ airports, selected, onSelect, tokens }) {
  const [hovered, setHovered] = useState(null);
  const projectable = airports.filter((a) => isProjectableUsCoordinate(a.lat, a.lon));
  const hidden = airports.length - projectable.length;
  const delayValues = projectable.map((a) => a.delay_pct);
  const minDelay = Math.min(...delayValues);
  const maxDelay = Math.max(...delayValues);
  const maxFlights = Math.max(...projectable.map((a) => a.total_flights));

  // Biggest first so small airports draw on top and stay clickable.
  const ordered = [...projectable].sort((a, b) => b.total_flights - a.total_flights);
  const hoverRow = projectable.find((a) => a.airport === hovered);

  return (
    <div className="map-frame">
      <ComposableMap projection="geoAlbersUsa" width={980} height={540} style={{ width: "100%", height: "auto" }}>
        <Geographies geography={US_MAP_TOPOJSON_URL}>
          {({ geographies }) =>
            geographies.map((geo) => (
              <Geography
                key={geo.rsmKey}
                geography={geo}
                fill={tokens.surface}
                stroke={tokens.hairline}
                strokeWidth={0.6}
                style={{ default: { outline: "none" }, hover: { outline: "none" }, pressed: { outline: "none" } }}
              />
            ))
          }
        </Geographies>
        <AirportDots
          airports={ordered}
          selected={selected}
          onSelect={onSelect}
          onHover={setHovered}
          maxFlights={maxFlights}
          minDelay={minDelay}
          maxDelay={maxDelay}
          tokens={tokens}
        />
      </ComposableMap>
      <p className="map-hover" aria-hidden="true">
        {hoverRow
          ? `${hoverRow.airport} · ${hoverRow.delay_pct}% late · ${hoverRow.total_flights.toLocaleString("en-US")} departures`
          : `${projectable.length} airports plotted${hidden ? `, ${hidden} outside the map projection` : ""}`}
      </p>
    </div>
  );
}

function dotRadius(flights, maxFlights) {
  // Area, not radius, tracks departures.
  return 1.5 + Math.sqrt(flights / maxFlights) * 14;
}

// Dots overlap in busy metros (MDW sits on top of ORD), so a click goes to
// whichever dot's center is relatively closest to the pointer, not just the
// topmost one. Clicking the middle of a big dot always selects that airport.
function AirportDots({ airports, selected, onSelect, onHover, maxFlights, minDelay, maxDelay, tokens }) {
  const { projection } = useMapContext();
  const placed = airports.map((airport) => {
    const [x, y] = projection([airport.lon, airport.lat]);
    return { airport, x, y, r: dotRadius(airport.total_flights, maxFlights) };
  });

  function resolve(event) {
    const svg = event.currentTarget.ownerSVGElement;
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(
      svg.getScreenCTM().inverse()
    );
    let best = null;
    for (const dot of placed) {
      const score = Math.hypot(point.x - dot.x, point.y - dot.y) / dot.r;
      if (score <= 1 && (!best || score < best.score)) best = { score, code: dot.airport.airport };
    }
    return best?.code ?? null;
  }

  return placed.map(({ airport, r }) => {
    const t = (airport.delay_pct - minDelay) / (maxDelay - minDelay || 1);
    const isSelected = airport.airport === selected;
    const dimmed = selected && !isSelected;
    return (
      <Marker key={airport.airport} coordinates={[airport.lon, airport.lat]}>
        <circle
          r={r}
          fill={mix(tokens.white, tokens.amber, t)}
          fillOpacity={dimmed ? 0.3 : 0.9}
          stroke={isSelected ? tokens.white : "#000000"}
          strokeWidth={isSelected ? 2 : 0.75}
          style={{ cursor: "pointer" }}
          data-airport={airport.airport}
          onClick={(e) => onSelect(resolve(e) ?? airport.airport)}
          onMouseMove={(e) => onHover(resolve(e) ?? airport.airport)}
          onMouseLeave={() => onHover(null)}
        >
          <title>
            {airport.airport}: {airport.delay_pct}% late, {airport.total_flights.toLocaleString("en-US")} departures
          </title>
        </circle>
        {isSelected && (
          <text
            y={-r - 6}
            textAnchor="middle"
            fill={tokens.white}
            fontFamily={tokens.font}
            fontSize={13}
            fontWeight={700}
            letterSpacing={1}
            style={{ pointerEvents: "none" }}
          >
            {airport.airport}
          </text>
        )}
      </Marker>
    );
  });
}

function DelayHeatmap({ cells, status, scope, tokens }) {
  const [hover, setHover] = useState(null);

  if (status === "loading") {
    return <div className="panel heatmap-card chart-note">Loading weekday × hour grid…</div>;
  }
  if (status === "error" || !cells) {
    return (
      <div className="panel heatmap-card chart-note dash-error" role="alert">
        Could not load the weekday × hour grid.
      </div>
    );
  }

  const byKey = new Map(cells.map((c) => [`${c.day_of_week}-${c.hour}`, c]));
  const rated = cells.filter((c) => c.total_flights >= MIN_FLIGHTS);
  const min = Math.min(...rated.map((c) => c.delay_pct));
  const max = Math.max(...rated.map((c) => c.delay_pct));
  const worst = rated.reduce((a, b) => (b.delay_pct > a.delay_pct ? b : a), rated[0]);
  const best = rated.reduce((a, b) => (b.delay_pct < a.delay_pct ? b : a), rated[0]);
  const slot = (c) => `${DAY_LABELS_SHORT[c.day_of_week]} ${String(c.hour).padStart(2, "0")}:00`;

  const readout = hover
    ? hover.total_flights >= MIN_FLIGHTS
      ? `${slot(hover)} · ${hover.delay_pct}% late · ${formatCount(hover.total_flights)} flights`
      : `${slot(hover)} · only ${formatCount(hover.total_flights)} flights, too few to rate`
    : `Worst slot ${slot(worst)} at ${worst.delay_pct}% · best ${slot(best)} at ${best.delay_pct}%`;

  return (
    <figure className="panel heatmap-card">
      <figcaption className="chart-card-head">
        <span className="board-label chart-card-title">Weekday × departure hour · {scope}</span>
        <span className="heatmap-legend">
          <span>{min}%</span>
          <span
            className="map-legend-gradient"
            style={{ background: `linear-gradient(90deg, ${HEATMAP_LOW}, ${tokens.amber})` }}
          />
          <span>{max}%</span>
        </span>
      </figcaption>

      <div
        className="heatmap"
        role="img"
        aria-label={`Delay rate by weekday and departure hour for ${scope}. ${readout}.`}
        onMouseLeave={() => setHover(null)}
      >
        <span />
        {HOURS.map((h) => (
          <span key={h} className="heatmap-hour">
            {h % 3 === 0 ? String(h).padStart(2, "0") : ""}
          </span>
        ))}
        {DAYS.map((d) => (
          <div key={d} className="heatmap-row">
            <span className="heatmap-day">{DAY_LABELS_SHORT[d].toUpperCase()}</span>
            {HOURS.map((h) => {
              const cell = byKey.get(`${d}-${h}`);
              const isRated = cell && cell.total_flights >= MIN_FLIGHTS;
              return (
                <span
                  key={h}
                  className={`heatmap-cell ${isRated ? "" : "heatmap-cell-empty"}`}
                  style={
                    isRated
                      ? { background: mix(HEATMAP_LOW, tokens.amber, (cell.delay_pct - min) / (max - min || 1)) }
                      : undefined
                  }
                  onMouseEnter={() => cell && setHover(cell)}
                />
              );
            })}
          </div>
        ))}
      </div>
      <p className="chart-note heatmap-readout">{readout}</p>
      {rated.length < DAYS.length * HOURS.length && (
        <p className="chart-note">
          Hatched cells have fewer than {MIN_FLIGHTS} flights and aren&apos;t rated.
        </p>
      )}
    </figure>
  );
}

const MODEL_METRICS = [
  { key: "auc", label: "AUC" },
  { key: "precision", label: "Precision" },
  { key: "recall", label: "Recall" },
  { key: "f1", label: "F1" },
];

function ModelTable({ comparison }) {
  return (
    <div className="panel model-card">
      <table className="model-table">
        <thead>
          <tr>
            <th scope="col" className="board-label">Model</th>
            {MODEL_METRICS.map((m) => (
              <th key={m.key} scope="col" className="board-label">
                {m.label}
              </th>
            ))}
            <th scope="col" className="board-label">Threshold</th>
          </tr>
        </thead>
        <tbody>
          {comparison.comparison.map((row) => {
            const best = row.model === comparison.best_model_by_f1;
            return (
              <tr key={row.model} className={best ? "model-best" : ""}>
                <th scope="row">
                  {row.model}
                  {best && <span className="model-flag">Best F1</span>}
                </th>
                {MODEL_METRICS.map((m) => (
                  <td key={m.key} data-label={m.label}>
                    <span className="model-value">{row[m.key].toFixed(4)}</span>
                    <span className="model-bar" aria-hidden="true">
                      <span style={{ width: `${row[m.key] * 100}%` }} />
                    </span>
                  </td>
                ))}
                <td data-label="Threshold">
                  <span className="model-value">{row.best_threshold.toFixed(2)}</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="chart-note">
        Best model by F1: <strong>{comparison.best_model_by_f1}</strong>, trained on{" "}
        {(comparison.train_rows / 1_000_000).toFixed(1)}M rows and evaluated on{" "}
        {(comparison.test_rows / 1_000_000).toFixed(2)}M held-out rows. Bars run from 0 to 1.
      </p>
    </div>
  );
}
