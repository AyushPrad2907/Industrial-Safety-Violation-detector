import React from 'react';
import { AlertOctagon, X, Clock, User, ShieldAlert } from 'lucide-react';

export function ViolationAlertBanner({ alerts, onDismiss }) {
  if (!alerts || alerts.length === 0) return null;

  return (
    <div className="fixed top-4 right-4 z-50 flex flex-col gap-3 max-w-md w-full pointer-events-none">
      {alerts.map((alert) => {
        const isCritical = alert.severity === 'CRITICAL';
        const borderColor = isCritical ? 'border-rose-500' : 'border-amber-500';
        const bgGlow = isCritical ? 'bg-rose-950/90 shadow-rose-950/50' : 'bg-amber-950/90 shadow-amber-950/50';

        return (
          <div
            key={alert.event_id}
            className={`pointer-events-auto border-2 ${borderColor} ${bgGlow} backdrop-blur-md rounded-xl p-4 shadow-2xl transition-all animate-bounce-short`}
          >
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-2">
                <div className={`p-2 rounded-lg ${isCritical ? 'bg-rose-500/20 text-rose-400' : 'bg-amber-500/20 text-amber-400'}`}>
                  <AlertOctagon className="w-6 h-6 animate-pulse" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold uppercase tracking-wider text-rose-400">
                      🚨 {alert.severity} SAFETY VIOLATION
                    </span>
                  </div>
                  <h3 className="text-base font-bold text-white">
                    {alert.violation_type}
                  </h3>
                </div>
              </div>
              <button
                onClick={() => onDismiss(alert.event_id)}
                className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition-colors"
                title="Dismiss"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="mt-3 pt-3 border-t border-slate-800 flex items-center justify-between text-xs text-slate-300">
              <span className="flex items-center gap-1">
                <User className="w-3.5 h-3.5 text-indigo-400" />
                Worker #{alert.track_id}
              </span>
              <span className="flex items-center gap-1">
                Score: <strong className="text-rose-300">{alert.decision_score}</strong>
              </span>
              <span className="flex items-center gap-1 text-slate-400">
                <Clock className="w-3.5 h-3.5" />
                {alert.timestamp ? alert.timestamp.split(' ')[1] : ''}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
