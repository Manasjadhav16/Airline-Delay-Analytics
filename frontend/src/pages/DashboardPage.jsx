import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  AlertTriangle,
  Clock,
  MapPin,
  Plane,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { fetchStats } from "../api";
import { MONTH_LABELS_SHORT, DAY_LABELS_SHORT } from "../constants";

const BAR_COLOR = "#0284c7";
const LINE_COLOR = "#d97706";

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
        Live aggregates from the cleaned 2015 US flight-delay dataset (5.7M flights).
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
    </div>
  );
}
