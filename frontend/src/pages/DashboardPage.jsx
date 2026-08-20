import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ComposableMap, Geographies, Geography, Marker } from "react-simple-maps";
import {
  AlertTriangle,
  Clock,
  GitCompare,
  Map as MapIcon,
  MapPin,
  Plane,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { fetchStats, fetchModelComparison, fetchAirportMap } from "../api";
import { MONTH_LABELS_SHORT, DAY_LABELS_SHORT } from "../constants";

const BAR_COLOR = "#0284c7";
const LINE_COLOR = "#d97706";

// Model comparison bars — stay within the established sky-blue / amber /
// success palette already used elsewhere (stat cards, result card) rather
// than introducing new hues.
const METRIC_COLORS = {
  auc: "#0284c7", // sky blue (primary)
  precision: "#0369a1", // primary-dark
  recall: "#15803d", // success green
  f1: "#b45309", // amber
};

const US_MAP_TOPOJSON_URL = "https://cdn.jsdelivr.net/npm/us-atlas@3/states-10m.json";

function delayColor(pct, minPct, maxPct) {
  const t = maxPct > minPct ? (pct - minPct) / (maxPct - minPct) : 0;
  // Interpolate sky-blue (low delay) -> amber (high delay), same two hues
  // already used throughout the dashboard for good/warning framing.
  const from = [2, 132, 199]; // #0284c7
  const to = [180, 83, 9]; // #b45309
  const rgb = from.map((c, i) => Math.round(c + (to[i] - c) * t));
  return `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
}

function ChartCard({ title, icon, children }) {
  return (
    <div className="chart-card">
      <h3>
        {icon}
        {title}
      </h3>
      <ResponsiveContainer width="100%" height={280}>
        {children}
      </ResponsiveContainer>
    </div>
  );
}

function StatCard({ icon, value, label, tone }) {
  return (
    <div className={`stat-card ${tone ?? ""}`}>
      <div className="stat-icon">{icon}</div>
      <div>
        <div className="stat-value">{value}</div>
        <div className="stat-label">{label}</div>
      </div>
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

  if (status === "loading") {
    return (
      <div className="page">
        <div className="alert alert-loading">
          <Plane size={16} className="icon-fly" /> Loading dashboard data...
        </div>
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="page">
        <div className="alert alert-error">
          Could not load dashboard data from the API: {error}
          <br />
          Is the backend running at the configured API_BASE_URL?
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <h1>Delay rate dashboard</h1>
      <p className="page-subtitle">
        Live aggregates from the cleaned 2015-2016 US flight-delay dataset (11.3M+ flights).
      </p>

      <div className="stats-bar">
        <StatCard
          icon={<Plane size={20} />}
          value={`${(summary.totalFlights / 1_000_000).toFixed(1)}M+`}
          label="Flights analyzed"
        />
        <StatCard
          icon={<TrendingUp size={20} />}
          value={`${summary.overallDelayPct.toFixed(2)}%`}
          label="Overall delay rate"
          tone="amber"
        />
        <StatCard
          icon={<AlertTriangle size={20} />}
          value={summary.worstAirline.name}
          label={`Worst airline (${summary.worstAirline.delay_pct}%)`}
          tone="red"
        />
        <StatCard
          icon={<MapPin size={20} />}
          value={summary.worstAirport.name}
          label={`Worst busy airport (${summary.worstAirport.delay_pct}%)`}
          tone="red"
        />
      </div>

      <div className="chart-grid">
        <ChartCard title="Delay rate by airline (%)" icon={<TrendingDown size={16} />}>
          <BarChart data={stats.airline} layout="vertical" margin={{ left: 40 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis type="number" unit="%" />
            <YAxis type="category" dataKey="name" width={160} tick={{ fontSize: 11 }} />
            <Tooltip formatter={(v) => `${v}%`} />
            <Bar dataKey="delay_pct" fill={BAR_COLOR} radius={[0, 4, 4, 0]} />
          </BarChart>
        </ChartCard>

        <ChartCard title="Delay rate at busiest airports (%)" icon={<MapPin size={16} />}>
          <BarChart data={stats.airport}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="name" tick={{ fontSize: 11 }} />
            <YAxis unit="%" />
            <Tooltip formatter={(v) => `${v}%`} />
            <Bar dataKey="delay_pct" fill={BAR_COLOR} radius={[4, 4, 0, 0]} />
          </BarChart>
        </ChartCard>

        <ChartCard title="Delay rate by scheduled departure hour (%)" icon={<Clock size={16} />}>
          <LineChart data={stats.hour}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="name" tick={{ fontSize: 11 }} />
            <YAxis unit="%" />
            <Tooltip formatter={(v) => `${v}%`} />
            <Line type="monotone" dataKey="delay_pct" stroke={LINE_COLOR} dot={{ r: 2 }} strokeWidth={2} />
          </LineChart>
        </ChartCard>

        <ChartCard title="Delay rate by day of week (%)" icon={<TrendingUp size={16} />}>
          <BarChart data={stats.dayofweek}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="label" />
            <YAxis unit="%" />
            <Tooltip formatter={(v) => `${v}%`} />
            <Bar dataKey="delay_pct" fill={BAR_COLOR} radius={[4, 4, 0, 0]} />
          </BarChart>
        </ChartCard>

        <ChartCard title="Delay rate by month (%)" icon={<TrendingUp size={16} />}>
          <LineChart data={stats.month}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="label" interval={0} tick={{ fontSize: 11 }} />
            <YAxis unit="%" />
            <Tooltip formatter={(v) => `${v}%`} />
            <Line type="monotone" dataKey="delay_pct" stroke={LINE_COLOR} dot={{ r: 3 }} strokeWidth={2} />
          </LineChart>
        </ChartCard>
      </div>

      <h2 className="section-heading">
        <GitCompare size={18} /> Model comparison
      </h2>
      <p className="page-subtitle">
        Logistic Regression vs Decision Tree vs Random Forest, each at its own
        best F1 threshold for the delayed class (from{" "}
        <code>src/model_v2.py</code>).
      </p>
      {modelComparisonStatus === "loading" && (
        <div className="alert alert-loading">
          <Plane size={16} className="icon-fly" /> Loading model comparison...
        </div>
      )}
      {modelComparisonStatus === "error" && (
        <div className="alert alert-error">Could not load model comparison data.</div>
      )}
      {modelComparisonStatus === "success" && modelComparison && (
        <div className="chart-card chart-card-wide">
          <ResponsiveContainer width="100%" height={320}>
            <BarChart data={modelComparison.comparison} margin={{ top: 8, right: 16 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="model" tick={{ fontSize: 12 }} />
              <YAxis domain={[0, 1]} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v) => v.toFixed(4)} />
              <Legend />
              <Bar dataKey="auc" name="AUC" fill={METRIC_COLORS.auc} radius={[3, 3, 0, 0]} />
              <Bar dataKey="precision" name="Precision" fill={METRIC_COLORS.precision} radius={[3, 3, 0, 0]} />
              <Bar dataKey="recall" name="Recall" fill={METRIC_COLORS.recall} radius={[3, 3, 0, 0]} />
              <Bar dataKey="f1" name="F1" fill={METRIC_COLORS.f1} radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
          <p className="chart-footnote">
            Best model by F1: <strong>{modelComparison.best_model_by_f1}</strong> —
            trained on {(modelComparison.train_rows / 1_000_000).toFixed(1)}M rows,
            evaluated on {(modelComparison.test_rows / 1_000).toFixed(0)}K held-out rows.
          </p>
        </div>
      )}

      <h2 className="section-heading">
        <MapIcon size={18} /> Airport delay map
      </h2>
      <p className="page-subtitle">
        Origin airports with 5,000+ flights, sized and colored by delay rate.
      </p>
      {airportMapStatus === "loading" && (
        <div className="alert alert-loading">
          <Plane size={16} className="icon-fly" /> Loading airport map...
        </div>
      )}
      {airportMapStatus === "error" && (
        <div className="alert alert-error">Could not load the airport map data.</div>
      )}
      {airportMapStatus === "success" && airportMap && (
        <div className="chart-card chart-card-wide">
          <AirportDelayMap airports={airportMap} />
        </div>
      )}
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

function AirportDelayMap({ airports }) {
  const projectable = airports.filter((a) => isProjectableUsCoordinate(a.lat, a.lon));
  const delayValues = projectable.map((a) => a.delay_pct);
  const minDelay = Math.min(...delayValues);
  const maxDelay = Math.max(...delayValues);

  return (
    <>
      <ComposableMap projection="geoAlbersUsa" width={980} height={500}>
        <Geographies geography={US_MAP_TOPOJSON_URL}>
          {({ geographies }) =>
            geographies.map((geo) => (
              <Geography
                key={geo.rsmKey}
                geography={geo}
                fill="#eef4fb"
                stroke="#c7d7e8"
                strokeWidth={0.75}
              />
            ))
          }
        </Geographies>
        {projectable.map((airport) => {
          const radius = 3 + ((airport.delay_pct - minDelay) / (maxDelay - minDelay || 1)) * 9;
          return (
            <Marker key={airport.airport} coordinates={[airport.lon, airport.lat]}>
              <circle
                r={radius}
                fill={delayColor(airport.delay_pct, minDelay, maxDelay)}
                fillOpacity={0.8}
                stroke="#ffffff"
                strokeWidth={0.75}
              >
                <title>
                  {airport.airport}: {airport.delay_pct}% delayed ({airport.total_flights.toLocaleString()} flights)
                </title>
              </circle>
            </Marker>
          );
        })}
      </ComposableMap>
      <div className="map-legend">
        <span>Lower delay</span>
        <span className="map-legend-gradient" />
        <span>Higher delay</span>
      </div>
    </>
  );
}
