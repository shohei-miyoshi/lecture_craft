import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import { AppErrorBoundary, AppRuntimeGuard } from "./components/AppRuntimeGuard.jsx";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <AppErrorBoundary>
      <AppRuntimeGuard>
        <App />
      </AppRuntimeGuard>
    </AppErrorBoundary>
  </React.StrictMode>
);
