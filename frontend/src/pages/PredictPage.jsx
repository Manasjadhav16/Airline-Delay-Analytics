import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Calendar,
  CheckCircle,
  Clock,
  MapPin,
  Plane,
  PlaneTakeoff,
  Ruler,
} from "lucide-react";
import { fetchMetadata, predictDelay } from "../api";
import { MONTHS, DAYS_OF_WEEK, HOURS } from "../constants";

const initialForm = {
  airline: "",
  origin_airport: "",
  month: 6,
  day_of_week: 1,
  scheduled_hour: 12,
  distance: 500,
};

export default function PredictPage() {
  const [metadata, setMetadata] = useState({ airlines: [], airports: [] });
  const [metadataError, setMetadataError] = useState(null);
  const [form, setForm] = useState(initialForm);
  const [status, setStatus] = useState("idle"); // idle | loading | success | error
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

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
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setStatus("loading");
    setError(null);
    setResult(null);
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
      <div className="page">
        <div className="alert alert-error">
          Could not load dropdown data from the API: {metadataError}
          <br />
          Is the backend running at the configured API_BASE_URL?
        </div>
      </div>
    );
  }

  const isDelayed = result?.prediction === "delayed";

  return (
    <div className="page">
      <div className="hero">
        <div className="hero-icon">
          <PlaneTakeoff size={30} strokeWidth={2} />
        </div>
        <h1>Will your flight be on time?</h1>
        <p className="page-subtitle">
          Enter flight details known before departure to get a delay prediction.
        </p>
      </div>

      <form className="predict-form" onSubmit={handleSubmit}>
        <div className="form-grid">
          <label className="form-field">
            <span className="form-field-label">
              <Plane size={14} /> Airline
            </span>
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

          <label className="form-field">
            <span className="form-field-label">
              <MapPin size={14} /> Origin airport
            </span>
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

          <label className="form-field">
            <span className="form-field-label">
              <Calendar size={14} /> Month
            </span>
            <select
              value={form.month}
              onChange={(e) => updateField("month", e.target.value)}
            >
              {MONTHS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>

          <label className="form-field">
            <span className="form-field-label">
              <Calendar size={14} /> Day of week
            </span>
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

          <label className="form-field">
            <span className="form-field-label">
              <Clock size={14} /> Scheduled departure hour
            </span>
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

          <label className="form-field">
            <span className="form-field-label">
              <Ruler size={14} /> Distance (miles)
            </span>
            <input
              type="number"
              min="1"
              value={form.distance}
              onChange={(e) => updateField("distance", e.target.value)}
              required
            />
          </label>
        </div>

        <button type="submit" className="submit-btn" disabled={status === "loading"}>
          {status === "loading" ? (
            <>
              <Plane size={16} className="icon-fly" /> Predicting...
            </>
          ) : (
            <>
              <PlaneTakeoff size={16} /> Predict delay
            </>
          )}
        </button>
      </form>

      {status === "error" && (
        <div className="alert alert-error">Prediction failed: {error}</div>
      )}

      {status === "success" && result && (
        <div
          key={`${result.prediction}-${result.probability}`}
          className={`result-card ${isDelayed ? "delayed" : "on-time"}`}
        >
          <div className="result-icon">
            {isDelayed ? (
              <AlertTriangle size={32} strokeWidth={2} />
            ) : (
              <CheckCircle size={32} strokeWidth={2} />
            )}
          </div>
          <div className="result-verdict">
            {isDelayed ? "Likely delayed" : "Likely on-time"}
          </div>
          <div className="result-probability">
            {(result.probability * 100).toFixed(1)}%
            <span className="result-probability-label">predicted delay probability</span>
          </div>
          <div className="result-note">{result.confidence_note}</div>
        </div>
      )}
    </div>
  );
}
