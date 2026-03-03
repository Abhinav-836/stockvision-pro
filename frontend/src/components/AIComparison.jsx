import React from 'react';
import { Brain, TrendingUp, Shield, DollarSign, Target, Zap } from 'lucide-react';

function AIComparison({ data, darkMode = true }) {
  if (!data) return null;

  const cards = [
    { key: 'best_for_growth', label: 'Best for Growth', icon: TrendingUp, color: 'emerald' },
    { key: 'best_for_value', label: 'Best for Value', icon: DollarSign, color: 'blue' },
    { key: 'best_for_income', label: 'Best for Income', icon: Target, color: 'yellow' },
    { key: 'safest_option', label: 'Safest Option', icon: Shield, color: 'purple' },
    { key: 'overall_recommendation', label: 'Top Pick', icon: Brain, color: 'emerald' }
  ];

  return (
    <div className="bg-gradient-to-br from-purple-900/20 to-indigo-900/20 rounded-xl p-6 border border-purple-500/30">
      <div className="flex items-center gap-3 mb-6">
        <Brain className="w-6 h-6 text-purple-400" />
        <h3 className="text-xl font-bold text-white">AI-Powered Analysis</h3>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
        {cards.map(({ key, label, icon: Icon, color }) => (
          <div
            key={key}
            className={`bg-slate-800/80 rounded-lg p-4 border border-${color}-500/20 hover:border-${color}-500/40 transition-all`}
          >
            <div className="flex items-center gap-2 mb-2">
              <Icon className={`w-4 h-4 text-${color}-400`} />
              <p className="text-sm text-slate-400">{label}</p>
            </div>
            <p className={`text-xl font-bold text-${color}-400`}>
              {data[key]}
            </p>
          </div>
        ))}
      </div>

      <div className="space-y-4">
        <div className="bg-slate-800/80 rounded-lg p-4">
          <h4 className="text-white font-semibold mb-2 flex items-center gap-2">
            <Zap className="w-4 h-4 text-purple-400" />
            Analysis
          </h4>
          <p className="text-slate-300">{data.analysis}</p>
        </div>

        <div className="bg-slate-800/80 rounded-lg p-4">
          <h4 className="text-white font-semibold mb-2">Risk Assessment</h4>
          <p className="text-slate-300">{data.risk_assessment}</p>
        </div>
      </div>
    </div>
  );
}

export default AIComparison;