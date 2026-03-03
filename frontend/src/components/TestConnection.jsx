import React from 'react';
import { AlertCircle, RefreshCw } from 'lucide-react';

function TestConnection({ onRetry }) {
  return (
    <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-6 mb-8">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center space-x-3">
          <AlertCircle className="w-6 h-6 text-red-400" />
          <div>
            <h3 className="text-lg font-semibold text-red-400">
              Backend Not Connected
            </h3>
            <p className="text-red-400/80 text-sm">
              Unable to connect to the server. Please ensure the backend is running.
            </p>
          </div>
        </div>
        <button
          onClick={onRetry}
          className="flex items-center space-x-2 px-4 py-2 bg-red-500/20 text-red-400 rounded-lg hover:bg-red-500/30 transition-colors"
        >
          <RefreshCw className="w-4 h-4" />
          <span>Retry Connection</span>
        </button>
      </div>
    </div>
  );
}

export default TestConnection;