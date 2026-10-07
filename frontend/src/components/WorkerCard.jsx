import React from 'react';
import { AlertTriangle, ShieldCheck, ShieldAlert, HardHat, Eye, Sparkles } from 'lucide-react';

export function WorkerCard({ worker }) {
  const { track_id, overall_status, confidence, ppe } = worker;

  const isConfirmed = overall_status === 'CONFIRMED';
  const isSuspected = overall_status === 'SUSPECTED';

  const badgeColor = isConfirmed
    ? 'bg-rose-500/20 text-rose-300 border-rose-500/30'
    : isSuspected
    ? 'bg-amber-500/20 text-amber-300 border-amber-500/30'
    : 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30';

  const badgeIcon = isConfirmed ? (
    <AlertTriangle className="w-4 h-4 text-rose-400" />
  ) : isSuspected ? (
    <ShieldAlert className="w-4 h-4 text-amber-400" />
  ) : (
    <ShieldCheck className="w-4 h-4 text-emerald-400" />
  );

  const ppeCategories = [
    { key: 'helmet', label: 'Safety Helmet' },
    { key: 'vest', label: 'Reflective Vest' },
    { key: 'gloves', label: 'Safety Gloves' },
    { key: 'boots', label: 'Safety Boots' },
    { key: 'goggles', label: 'Eye Goggles' },
  ];

  return (
    <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4 shadow-lg backdrop-blur-sm transition-all hover:border-slate-700">
      <div className="flex items-center justify-between pb-3 border-b border-slate-800/80">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-indigo-500/20 border border-indigo-500/30 flex items-center justify-center font-bold text-indigo-400">
            #{track_id}
          </div>
          <div>
            <h4 className="font-semibold text-slate-100 text-sm">Worker #{track_id}</h4>
            <span className="text-xs text-slate-400">Conf: {(confidence * 100).toFixed(0)}%</span>
          </div>
        </div>
        <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border ${badgeColor}`}>
          {badgeIcon}
          <span>{overall_status}</span>
        </div>
      </div>

      {/* PPE Items Grid */}
      <div className="mt-3 space-y-2">
        {ppeCategories.map(({ key, label }) => {
          const item = ppe?.[key] || { state: 'UNKNOWN', temporal_status: 'NORMAL' };
          const state = item.state; // PRESENT, NOT_ASSOCIATED, UNKNOWN
          const tempStatus = item.temporal_status;

          let stateBadge = null;
          if (state === 'PRESENT') {
            stateBadge = (
              <span className="inline-flex items-center gap-1 text-xs text-emerald-400 font-medium">
                ✅ PRESENT
              </span>
            );
          } else if (state === 'NOT_ASSOCIATED') {
            stateBadge = (
              <span className="inline-flex items-center gap-1 text-xs text-rose-400 font-medium">
                ❌ NOT ASSOCIATED
              </span>
            );
          } else {
            stateBadge = (
              <span className="inline-flex items-center gap-1 text-xs text-slate-400 font-medium">
                ❓ UNKNOWN
              </span>
            );
          }

          let tempTag = null;
          if (tempStatus === 'CONFIRMED') {
            tempTag = <span className="text-[10px] px-1.5 py-0.5 rounded bg-rose-950 text-rose-300 border border-rose-800">Confirmed Missing</span>;
          } else if (tempStatus === 'SUSPECTED') {
            tempTag = <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-950 text-amber-300 border border-amber-800">Suspected</span>;
          }

          return (
            <div key={key} className="flex items-center justify-between text-xs py-1 px-2 rounded-lg bg-slate-800/40 border border-slate-800/40">
              <span className="text-slate-300 font-medium">{label}</span>
              <div className="flex items-center gap-2">
                {tempTag}
                {stateBadge}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
