import React, { useState } from 'react';
import {
  Lightbulb,
  TrendingUp,
  Shield,
  DollarSign,
  BarChart3,
  Target,
  Clock,
  PieChart,
  Zap,
  BookOpen,
  AlertTriangle,
  RefreshCw,
  Building,
  Search,
  Calendar,
  Waves
} from 'lucide-react';

function AnalysisTips({ darkMode = true }) {
  const [category, setCategory] = useState('all');

  const tips = {
    valuation: [
      {
        icon: BarChart3,
        text: "P/E ratio shows valuation relative to earnings",
        emphasis: "Lower P/E may indicate undervaluation"
      },
      {
        icon: BookOpen,
        text: "P/B ratio compares price to net asset value",
        emphasis: "P/B < 1 suggests undervaluation"
      }
    ],
    growth: [
      {
        icon: TrendingUp,
        text: "Focus on consistent earnings growth",
        emphasis: "Look for 10%+ annual EPS growth"
      },
      {
        icon: Zap,
        text: "Revenue growth indicates expansion",
        emphasis: "Sustainable growth beats spikes"
      }
    ],
    risk: [
      {
        icon: Shield,
        text: "Debt-to-equity measures financial stability",
        emphasis: "Keep below 2 for most industries"
      },
      {
        icon: Waves,
        text: "Beta shows volatility relative to market",
        emphasis: "Beta > 1 = more volatile"
      },
      {
        icon: PieChart,
        text: "Diversify across sectors",
        emphasis: "Don't put all eggs in one basket"
      }
    ],
    dividends: [
      {
        icon: DollarSign,
        text: "Dividend yield shows annual return",
        emphasis: "Sustainable payout ratio is key"
      },
      {
        icon: Target,
        text: "Dividend growth indicates health",
        emphasis: "Look for consistent increases"
      }
    ],
    strategy: [
      {
        icon: Clock,
        text: "Time horizon determines risk level",
        emphasis: "Long-term = growth, Short-term = stability"
      },
      {
        icon: RefreshCw,
        text: "Rebalance periodically",
        emphasis: "Quarterly or annual rebalancing"
      },
      {
        icon: Search,
        text: "Look for undervalued stocks",
        emphasis: "Margin of safety principle"
      }
    ]
  };

  const allTips = Object.values(tips).flat();
  const categories = [
    { id: 'all', label: 'All Tips', icon: Lightbulb, count: allTips.length },
    { id: 'valuation', label: 'Valuation', icon: BarChart3, count: tips.valuation.length },
    { id: 'growth', label: 'Growth', icon: TrendingUp, count: tips.growth.length },
    { id: 'risk', label: 'Risk', icon: Shield, count: tips.risk.length },
    { id: 'dividends', label: 'Dividends', icon: DollarSign, count: tips.dividends.length },
    { id: 'strategy', label: 'Strategy', icon: Target, count: tips.strategy.length }
  ];

  const displayTips = category === 'all' ? allTips : tips[category];

  return (
    <div className={`rounded-xl p-6 border ${
      darkMode ? 'bg-slate-800 border-slate-700' : 'bg-white border-slate-200'
    } shadow-lg`}>
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <div className="p-2 bg-gradient-to-r from-amber-500 to-orange-500 rounded-lg">
          <Lightbulb className="w-6 h-6 text-white" />
        </div>
        <div>
          <h3 className="text-xl font-bold">Investment Analysis Guide</h3>
          <p className={darkMode ? 'text-slate-400' : 'text-slate-500'}>
            Essential metrics for smart investing
          </p>
        </div>
      </div>

      {/* Categories */}
      <div className="flex flex-wrap gap-2 mb-6">
        {categories.map(cat => (
          <button
            key={cat.id}
            onClick={() => setCategory(cat.id)}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-all ${
              category === cat.id
                ? 'bg-emerald-500 text-white shadow-lg'
                : darkMode
                  ? 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                  : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
            }`}
          >
            <cat.icon className="w-4 h-4" />
            {cat.label}
            <span className={`px-1.5 py-0.5 rounded text-xs ${
              category === cat.id
                ? 'bg-white/20'
                : darkMode ? 'bg-slate-600' : 'bg-slate-200'
            }`}>
              {cat.count}
            </span>
          </button>
        ))}
      </div>

      {/* Tips Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {displayTips.map((tip, index) => (
          <div
            key={index}
            className={`rounded-lg p-4 border transition-all hover:shadow-md ${
              darkMode
                ? 'bg-slate-700/50 border-slate-600 hover:border-slate-500'
                : 'bg-slate-50 border-slate-200 hover:border-slate-300'
            }`}
          >
            <div className="flex items-start gap-3">
              <div className={`p-2 rounded-lg ${
                darkMode ? 'bg-slate-600' : 'bg-white'
              }`}>
                <tip.icon className="w-4 h-4 text-emerald-400" />
              </div>
              <div className="flex-1">
                <p className="font-medium mb-2">{tip.text}</p>
                <p className="text-emerald-400 text-sm font-semibold bg-emerald-400/10 px-3 py-1 rounded border border-emerald-400/20">
                  {tip.emphasis}
                </p>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Footer */}
      <div className={`mt-6 pt-4 border-t flex justify-between text-sm ${
        darkMode ? 'border-slate-700 text-slate-400' : 'border-slate-200 text-slate-500'
      }`}>
        <span>{displayTips.length} investment insights</span>
        <span className="px-2 py-1 bg-slate-700 rounded">Updated daily</span>
      </div>
    </div>
  );
}

export default AnalysisTips;