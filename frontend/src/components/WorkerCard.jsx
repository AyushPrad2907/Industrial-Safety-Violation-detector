import React from 'react';

export function WorkerCard({ worker }) {
  const { track_id, overall_status, confidence, ppe } = worker;

  const isConfirmed = overall_status === 'CONFIRMED';
  const isSuspected = overall_status === 'SUSPECTED';

  const statusBg = isConfirmed
    ? 'bg-[#FF2A2A] text-black font-black'
    : isSuspected
    ? 'bg-[#EAB308] text-black font-black'
    : 'bg-[#00FF66] text-black font-bold';

  const borderClass = isConfirmed
    ? 'border-[#FF2A2A]'
    : isSuspected
    ? 'border-[#EAB308]'
    : 'border-[#262626]';

  const ppeCategories = [
    { key: 'helmet', label: 'HARDHAT / HELMET' },
    { key: 'vest', label: 'HI-VIS SAFETY VEST' },
    { key: 'gloves', label: 'TACTILE GLOVES' },
    { key: 'boots', label: 'STEEL-TOE BOOTS' },
    { key: 'goggles', label: 'SAFETY GOGGLES' },
  ];

  return (
    <div className={`bg-[#0D0D0D] border ${borderClass} p-3 font-mono transition-colors`}>
      {/* Header bar */}
      <div className="flex items-center justify-between pb-2 border-b border-[#262626] text-xs">
        <div className="flex items-center gap-2">
          <span className="bg-[#1A1A1A] text-[#E5E5E5] px-1.5 py-0.5 border border-[#333] font-bold">
            W-{String(track_id).padStart(2, '0')}
          </span>
          <span className="text-[#888] tracking-widest text-[11px]">
            CONF: {(confidence * 100).toFixed(0)}%
          </span>
        </div>
        <span className={`px-2 py-0.5 text-[10px] tracking-wider uppercase ${statusBg}`}>
          [{overall_status}]
        </span>
      </div>

      {/* PPE Items List */}
      <div className="mt-2.5 space-y-1.5 text-xs">
        {ppeCategories.map(({ key, label }) => {
          const item = ppe?.[key] || { state: 'UNKNOWN', temporal_status: 'NORMAL' };
          const state = item.state;
          const tempStatus = item.temporal_status;

          let stateColor = 'text-[#666]';
          let stateTag = '[ UNKNOWN ]';

          if (state === 'PRESENT') {
            stateColor = 'text-[#00FF66]';
            stateTag = '✓ PRESENT';
          } else if (state === 'NOT_ASSOCIATED') {
            stateColor = 'text-[#FF2A2A]';
            stateTag = '✕ MISSING';
          }

          let temporalTag = null;
          if (tempStatus === 'CONFIRMED') {
            temporalTag = <span className="text-[10px] bg-[#FF2A2A]/20 text-[#FF2A2A] px-1 border border-[#FF2A2A]/40 uppercase">CONFIRMED</span>;
          } else if (tempStatus === 'SUSPECTED') {
            temporalTag = <span className="text-[10px] bg-[#EAB308]/20 text-[#EAB308] px-1 border border-[#EAB308]/40 uppercase">SUSPECTED</span>;
          }

          return (
            <div
              key={key}
              className="flex items-center justify-between py-1 px-2 bg-[#121212] border border-[#1F1F1F] text-[11px]"
            >
              <span className="text-[#A3A3A3] font-mono">{label}</span>
              <div className="flex items-center gap-2">
                {temporalTag}
                <span className={`font-mono font-bold ${stateColor}`}>
                  {stateTag}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
