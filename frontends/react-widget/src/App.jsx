import { useState } from "react";
import { ChatWidget } from "./widget/ChatWidget.jsx";
import { AdminProvider } from "./admin/AdminContext.jsx";
import { AdminDashboard } from "./admin/AdminDashboard.jsx";

export function App() {
  const [tab, setTab] = useState("chat");
  return (
    <AdminProvider>
      <div className="app-shell-wide">
        <div className="top-nav">
          <button className={tab === "chat" ? "active" : ""} onClick={() => setTab("chat")}>
            Chat
          </button>
          <button className={tab === "admin" ? "active" : ""} onClick={() => setTab("admin")}>
            Admin
          </button>
        </div>
        {tab === "chat" ? <ChatWidget /> : null}
        {tab === "admin" ? <AdminDashboard /> : null}
      </div>
    </AdminProvider>
  );
}
