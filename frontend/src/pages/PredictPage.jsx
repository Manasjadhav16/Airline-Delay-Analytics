import { useEffect, useRef, useState } from "react";
import { fetchMetadata, predictDelay } from "../api";
import {
  AIRLINE_CODES,
  DAY_LABELS_SHORT,
  DAYS_OF_WEEK,
  HOURS,
  MONTH_LABELS_SHORT,
  MONTHS,
} from "../constants";
import SplitFlap from "../components/SplitFlap";
import "./PredictPage.css";

const initialForm = {
  airline: "",
  origin_airport: "",
  month: 6,
  day_of_week: 1,
  scheduled_hour: 12,
  distance: 500,
};

function formatClock(date) {
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function formatChance(probability) {
  const pct = probability * 100;
  return pct >= 99.95 ? "100%" : `${pct.toFixed(1)}%`;
}

function useClock() {
  const [now, setNow] = useState(() => formatClock(new Date()));
  useEffect(() => {
    const id = setInterval(() => setNow(formatClock(new Date())), 10_000);
    return () => clearInterval(id);
  }, []);
  return now;
}

export default function PredictPage() {
  const [metadata, setMetadata] = useState({ airlines: [], airports: [] });
  const [metadataError, setMetadataError] = useState(null);
  const [form, setForm] = useState(initialForm);
  const [status, setStatus] = useState("idle"); // idle | loading | success | error
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const boardRef = useRef(null);
  const clock = useClock();

  useEffect(() => {
    fetchMetadata()
      .then((data) => {
        setMetadata(data);
        setForm((prev) => ({
          ...prev,
          airline: data.airlines[0] ?? "",
          origin_airport: data.airports[0] ?? "",
        }));
      })
      .catch((err) => setMetadataError(err.message));
  }, []);

  function updateField(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
    // Any edit makes the previous verdict stale.
    if (status === "success" || status === "error") {
      setStatus("idle");
      setResult(null);
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setStatus("loading");
    setError(null);
    setResult(null);

    // On narrow screens the board is above the fold-out form; bring it back.
    const board = boardRef.current;
    if (board && board.getBoundingClientRect().top < 0) {
      board.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    try {
      const payload = {
        airline: form.airline,
        origin_airport: form.origin_airport,
        month: Number(form.month),
        day_of_week: Number(form.day_of_week),
        scheduled_hour: Number(form.scheduled_hour),
        distance: Number(form.distance),
      };
      const data = await predictDelay(payload);
      setResult(data);
      setStatus("success");
    } catch (err) {
      setError(err.message);
      setStatus("error");
    }
  }

  if (metadataError) {
    return (
      <div className="board-page">
        <div className="page-inner">
          <p className="board-eyebrow">Departures</p>
          <h1 className="board-title">Board offline</h1>
          <p className="board-message board-message-error" role="alert">
            Could not load airlines and airports from the API: {metadataError}. Check that the
            backend is running at the configured API_BASE_URL.
          </p>
        </div>
      </div>
    );
  }

  const isDelayed = result?.prediction === "delayed";
  const statusText = {
    idle: "",
    loading: "CHECKING",
    success: isDelayed ? "DELAYED" : "ON TIME",
    error: "NO DATA",
  }[status];
  const chanceText = status === "success" ? formatChance(result.probability) : "";
  const airlineCode = AIRLINE_CODES[form.airline] ?? form.airline.slice(0, 2);
  const miles = Number(form.distance) > 0 ? String(Math.round(Number(form.distance))) : "";

  return (
    <div className="board-page">
      <div className="page-inner">
        <header className="board-head">
          <div>
            <p className="board-eyebrow">Delay forecast · 2015–2016 U.S. domestic flights</p>
            <h1 className="board-title">Departures</h1>
          </div>
          <div className="board-clock">
            <span className="board-label">Local time</span>
            <SplitFlap value={clock} length={5} stagger={30} />
          </div>
        </header>

        <section
          ref={boardRef}
          className={`board status-${status} ${isDelayed ? "is-delayed" : ""}`}
          aria-label="Departure board"
        >
          <div className="board-row">
            <div className="board-cell cell-time">
              <span className="board-label">Time</span>
              <SplitFlap value={`${String(form.scheduled_hour).padStart(2, "0")}:00`} length={5} />
            </div>
            <div className="board-cell cell-airline">
              <span className="board-label">Airline</span>
              <SplitFlap value={airlineCode} length={2} />
            </div>
            <div className="board-cell cell-from">
              <span className="board-label">From</span>
              <SplitFlap value={form.origin_airport} length={3} />
            </div>
            <div className="board-cell cell-month">
              <span className="board-label">Month</span>
              <SplitFlap value={MONTH_LABELS_SHORT[form.month]} length={3} />
            </div>
            <div className="board-cell cell-day">
              <span className="board-label">Day</span>
              <SplitFlap value={DAY_LABELS_SHORT[form.day_of_week]} length={3} />
            </div>
            <div className="board-cell cell-miles">
              <span className="board-label">Miles</span>
              <SplitFlap value={miles} length={4} align="right" />
            </div>
            <div className="board-cell cell-status" aria-live="polite">
              <span className="board-label">Status</span>
              <SplitFlap value={statusText} length={8} className="flap-status" />
            </div>
            <div className="board-cell cell-chance" aria-live="polite">
              <span className="board-label">Delay chance</span>
              <SplitFlap value={chanceText} length={5} align="right" className="flap-status" />
            </div>
          </div>

          {status === "idle" && (
            <p className="board-message">
              The board mirrors your flight below. Check it to flip the status.
            </p>
          )}
          {status === "loading" && <p className="board-message">Asking the model…</p>}
          {status === "success" && <p className="board-message">{result.confidence_note}</p>}
          {status === "error" && (
            <p className="board-message board-message-error" role="alert">
              Prediction failed: {error}
            </p>
          )}
        </section>

        <form className="checkin" onSubmit={handleSubmit}>
          <div className="checkin-head">
            <h2 className="section-title">Your flight</h2>
            <p className="lede checkin-lede">
              Only details known before departure. Nothing measured after pushback goes into
              the model.
            </p>
          </div>

          <div className="checkin-grid">
            <label className="field field-airline">
              <span className="board-label">Airline</span>
              <select
                value={form.airline}
                onChange={(e) => updateField("airline", e.target.value)}
                required
              >
                {metadata.airlines.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </label>

            <label className="field">
              <span className="board-label">Origin airport</span>
              <select
                value={form.origin_airport}
                onChange={(e) => updateField("origin_airport", e.target.value)}
                required
              >
                {metadata.airports.map((code) => (
                  <option key={code} value={code}>
                    {code}
                  </option>
                ))}
              </select>
            </label>

            <label className="field">
              <span className="board-label">Departure hour</span>
              <select
                value={form.scheduled_hour}
                onChange={(e) => updateField("scheduled_hour", e.target.value)}
              >
                {HOURS.map((h) => (
                  <option key={h} value={h}>
                    {String(h).padStart(2, "0")}:00
                  </option>
                ))}
              </select>
            </label>

            <label className="field">
              <span className="board-label">Month</span>
              <select value={form.month} onChange={(e) => updateField("month", e.target.value)}>
                {MONTHS.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="field">
              <span className="board-label">Day of week</span>
              <select
                value={form.day_of_week}
                onChange={(e) => updateField("day_of_week", e.target.value)}
              >
                {DAYS_OF_WEEK.map((d) => (
                  <option key={d.value} value={d.value}>
                    {d.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="field">
              <span className="board-label">Distance (miles)</span>
              <input
                type="number"
                min="1"
                max="9999"
                inputMode="numeric"
                value={form.distance}
                onChange={(e) => updateField("distance", e.target.value)}
                required
              />
            </label>
          </div>

          <button type="submit" className="ghost-pill" disabled={status === "loading"}>
            {status === "loading" ? "Checking…" : "Check status"}
          </button>
        </form>
      </div>
    </div>
  );
}
