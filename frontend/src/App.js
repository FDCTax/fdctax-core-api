import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "./components/ui/sonner";

/**
 * FDC Tax Core - API Only Mode
 * 
 * This frontend has been disabled. The Core backend is API-only.
 * All authentication is handled via:
 * - Internal API Keys (X-Internal-Api-Key header)
 * - Service tokens from Secret Authority
 * 
 * API Documentation: /api/docs (when debug mode is enabled)
 */

function APIOnlyPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-900 text-white p-4">
      <div className="text-center max-w-lg">
        <h1 className="text-3xl font-bold mb-4">FDC Tax Core</h1>
        <p className="text-slate-400 mb-6">
          This service operates in API-only mode.
        </p>
        <div className="bg-slate-800 rounded-lg p-6 text-left">
          <h2 className="text-lg font-semibold mb-3 text-slate-200">API Endpoints</h2>
          <ul className="space-y-2 text-sm text-slate-400">
            <li><code className="text-green-400">/api/health</code> - Health check</li>
            <li><code className="text-green-400">/api/core/status</code> - Core module status</li>
            <li><code className="text-green-400">/api/docs</code> - API documentation</li>
          </ul>
          <div className="mt-4 pt-4 border-t border-slate-700">
            <p className="text-xs text-slate-500">
              Authentication: Internal API Keys or Service Tokens
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <Routes>
          {/* All routes show API-only message */}
          <Route path="*" element={<APIOnlyPage />} />
        </Routes>
        <Toaster />
      </BrowserRouter>
    </div>
  );
}

export default App;
