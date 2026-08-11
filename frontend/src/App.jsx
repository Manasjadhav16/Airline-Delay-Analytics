import { useState } from "react";
import Nav from "./components/Nav";
import PredictPage from "./pages/PredictPage";
import DashboardPage from "./pages/DashboardPage";
import "./App.css";

function App() {
  const [activeTab, setActiveTab] = useState("predict");

  return (
    <div className="app">
      <Nav activeTab={activeTab} onTabChange={setActiveTab} />
      <main>
        <div className="page-transition" key={activeTab}>
          {activeTab === "predict" ? <PredictPage /> : <DashboardPage />}
        </div>
      </main>
    </div>
  );
}

export default App;
