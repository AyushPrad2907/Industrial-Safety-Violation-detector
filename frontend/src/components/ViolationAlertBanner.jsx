import React from 'react';

export function ViolationAlertBanner({ alerts, onDismiss }) {
  if (!alerts || alerts.length === 0) return null;

  return (
    <div className="fixed top-3 right-3 z-50 flex flex-col gap-2 max-w-sm w-full font-mono">
      {alerts.map((alert) => {
        const isCritical = alert.severity === 'CRITICAL';
        const borderColor = isCritical ? 'border-[#FF2A2A]' : 'border-[#EAB308]';
        const headerBg = isCritical ? 'bg-[#FF2A2A] text-black' : 'bg-[#EAB308] text-black';

        return (
          <div
            key={alert.event_id}
            className={`border-2 ${borderColor} bg-[#0A0A0A] shadow-[0_0_20px_rgba(255,42,42,0.25)] text-xs`}
          >
            {/* Header */}
            <div className={`flex items-center justify-between px-2.5 py-1 font-black uppercase text-[11px] ${headerBg}`}>
              <span>/// ALERT : {alert.severity}</span>
              <button
                onClick={() => onDismiss(alert.event_id)}
                className="hover:bg-black/20 px-1 font-black"
                title="Dismiss"
              >
                [X]
              </button>
            </div>

            {/* Body */}
            <div className="p-3 space-y-1.5 text-[#E5E5E5]">
              <div className="text-sm font-bold tracking-wider text-white">
                {alert.violation_type}
              </div>
              <div className="flex items-center justify-between text-[11px] text-[#888] pt-1 border-t border-[#222]">
                <span>WORKER: <strong className="text-white">#{alert.track_id}</strong></span>
                <span>SCORE: <strong className="text-[#FF2A2A]">{alert.decision_score}</strong></span>
                <span>{alert.timestamp ? alert.timestamp.split(' ')[1] : ''}</span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
