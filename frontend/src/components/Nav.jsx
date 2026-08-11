import { Plane } from "lucide-react";

export default function Nav({ activeTab, onTabChange }) {
  return (
    <nav className="nav">
      <div className="nav-brand">
        <Plane size={20} strokeWidth={2.25} />
        <span>Airline Delay Analytics</span>
      </div>
      <div className="nav-tabs">
        <button
          className={`nav-tab ${activeTab === "predict" ? "active" : ""}`}
          onClick={() => onTabChange("predict")}
        >
          Predict
        </button>
        <button
          className={`nav-tab ${activeTab === "dashboard" ? "active" : ""}`}
          onClick={() => onTabChange("dashboard")}
        >
          Dashboard
        </button>
      </div>
    </nav>
  );
}
