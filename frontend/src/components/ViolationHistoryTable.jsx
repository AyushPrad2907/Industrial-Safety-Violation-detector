import React, { useState } from 'react';
import { getCsvExportUrl, getEvidenceUrl } from '../services/api';

export function ViolationHistoryTable({ violations, onRefresh, loading }) {
  const [selectedSeverity, setSelectedSeverity] = useState('All');
  const [selectedType, setSelectedType] = useState('All');
  const [selectedWorker, setSelectedWorker] = useState('All');
  const [expandedRow, setExpandedRow] = useState(null);

  const workerOptions = ['All', ...new Set(violations.map((v) => String(v.track_id)))].sort();
  const typeOptions = ['All', 'Missing Helmet', 'Missing Vest', 'Missing Gloves', 'Missing Boots', 'Missing Goggles'];
  const severityOptions = ['All', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];

  const filteredViolations = violations.filter((v) => {
    if (selectedSeverity !== 'All' && v.severity.toUpperCase() !== selectedSeverity) return false;
    if (selectedType !== 'All' && v.violation_type.toLowerCase() !== selectedType.toLowerCase()) return false;
    if (selectedWorker !== 'All' && String(v.track_id) !== selectedWorker) return false;
    return true;
  });

  const exportUrl = getCsvExportUrl({
    severity: selectedSeverity,
    violation_type: selectedType,
    worker_id: selectedWorker,
  });

  const toggleExpand = (eventId) => {
    setExpandedRow(expandedRow === eventId ? null : eventId);
  };

  return (
    <div className="bg-[#0A0A0A] border border-[#222] font-mono text-xs">
      {/* Title & Action Bar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between p-4 border-b border-[#222] gap-3 bg-[#0D0D0D]">
        <div>
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 bg-[#FF2A2A]"></span>
            <h2 className="text-sm font-bold tracking-widest uppercase text-white">
              [ LOG // CONFIRMED SAFETY VIOLATIONS ]
            </h2>
          </div>
          <p className="text-[11px] text-[#666] mt-0.5">
            SQLITE RECORD STORE • EVIDENCE CAPTURE ARCHIVE
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={onRefresh}
            disabled={loading}
            className="px-3 py-1.5 bg-[#141414] hover:bg-[#202020] text-[#CCC] border border-[#333] tracking-wider uppercase transition-colors"
          >
            {loading ? '[ SYNCING... ]' : '[ REFRESH ]'}
          </button>
          <a
            href={exportUrl}
            download="violation_history.csv"
            className="px-3.5 py-1.5 bg-[#FF2A2A] hover:bg-[#E01E1E] text-black font-bold tracking-wider uppercase transition-colors"
          >
            EXPORT CSV &gt;&gt;
          </a>
        </div>
      </div>

      {/* Filter Parameters Strip */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 p-3 bg-[#080808] border-b border-[#222]">
        <div>
          <label className="block text-[10px] text-[#777] mb-1 uppercase tracking-wider">
            FILTER: SEVERITY
          </label>
          <select
            value={selectedSeverity}
            onChange={(e) => setSelectedSeverity(e.target.value)}
            className="w-full bg-[#111] border border-[#333] px-2.5 py-1 text-xs text-white focus:outline-none focus:border-[#FF2A2A]"
          >
            {severityOptions.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-[10px] text-[#777] mb-1 uppercase tracking-wider">
            FILTER: VIOLATION TYPE
          </label>
          <select
            value={selectedType}
            onChange={(e) => setSelectedType(e.target.value)}
            className="w-full bg-[#111] border border-[#333] px-2.5 py-1 text-xs text-white focus:outline-none focus:border-[#FF2A2A]"
          >
            {typeOptions.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-[10px] text-[#777] mb-1 uppercase tracking-wider">
            FILTER: TARGET WORKER
          </label>
          <select
            value={selectedWorker}
            onChange={(e) => setSelectedWorker(e.target.value)}
            className="w-full bg-[#111] border border-[#333] px-2.5 py-1 text-xs text-white focus:outline-none focus:border-[#FF2A2A]"
          >
            {workerOptions.map((w) => (
              <option key={w} value={w}>{w === 'All' ? 'ALL TRACKED WORKERS' : `WORKER #${w}`}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Summary status line */}
      <div className="px-4 py-2 text-[11px] text-[#666] border-b border-[#1A1A1A] flex justify-between">
        <span>ENTRIES: <strong className="text-white">{filteredViolations.length}</strong> / {violations.length} TOTAL</span>
        <span>AUDIT STATE: ACTIVE</span>
      </div>

      {/* Table */}
      {filteredViolations.length === 0 ? (
        <div className="p-12 text-center text-[#555] bg-[#070707]">
          [ NO VIOLATION RECORDS MATCH CURRENT AUDIT PARAMETERS ]
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-[#111] text-[10px] tracking-wider uppercase text-[#888] border-b border-[#222]">
                <th className="py-2.5 px-3">TIMESTAMP</th>
                <th className="py-2.5 px-3">WORKER ID</th>
                <th className="py-2.5 px-3">VIOLATION TYPE</th>
                <th className="py-2.5 px-3">SEVERITY</th>
                <th className="py-2.5 px-3">SCORE</th>
                <th className="py-2.5 px-3">ZONE</th>
                <th className="py-2.5 px-3 text-right">EVIDENCE</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#181818]">
              {filteredViolations.map((v) => {
                const isCrit = v.severity === 'CRITICAL';
                const isHigh = v.severity === 'HIGH';
                const sevClass = isCrit
                  ? 'text-[#FF2A2A] font-bold'
                  : isHigh
                  ? 'text-[#EAB308] font-bold'
                  : 'text-[#888]';

                const isExpanded = expandedRow === v.event_id;

                return (
                  <React.Fragment key={v.event_id}>
                    <tr className="hover:bg-[#121212] transition-colors">
                      <td className="py-2.5 px-3 text-[#777]">{v.timestamp}</td>
                      <td className="py-2.5 px-3 font-bold text-white">W-{String(v.track_id).padStart(2, '0')}</td>
                      <td className="py-2.5 px-3 text-[#DDD]">{v.violation_type}</td>
                      <td className={`py-2.5 px-3 ${sevClass}`}>[{v.severity}]</td>
                      <td className="py-2.5 px-3 text-[#888]">{v.decision_score}</td>
                      <td className="py-2.5 px-3">
                        {v.is_zone_violation ? (
                          <span className="text-[#FF2A2A] font-bold">YES</span>
                        ) : (
                          <span className="text-[#444]">NO</span>
                        )}
                      </td>
                      <td className="py-2.5 px-3 text-right">
                        <button
                          onClick={() => toggleExpand(v.event_id)}
                          className="px-2 py-0.5 bg-[#1C1C1C] hover:bg-[#2A2A2A] text-[#CCC] border border-[#333] text-[10px] uppercase tracking-wider"
                        >
                          {isExpanded ? '[-] HIDE' : '[+] VIEW'}
                        </button>
                      </td>
                    </tr>

                    {/* Evidence Drawer */}
                    {isExpanded && (
                      <tr className="bg-[#050505] border-y border-[#262626]">
                        <td colSpan={7} className="p-4">
                          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 border border-[#222] p-3 bg-[#0A0A0A]">
                            <div className="md:col-span-1 border border-[#333] bg-black">
                              <img
                                src={getEvidenceUrl(v.event_id)}
                                alt={`Evidence ${v.event_id}`}
                                className="w-full h-auto block"
                                onError={(e) => {
                                  e.target.style.display = 'none';
                                  e.target.nextSibling.style.display = 'block';
                                }}
                              />
                              <div
                                style={{ display: 'none' }}
                                className="p-6 text-center text-[#FF2A2A] text-[11px]"
                              >
                                [ EVIDENCE FILE UNAVAILABLE ]
                              </div>
                            </div>

                            <div className="md:col-span-2 space-y-2 text-[11px]">
                              <div className="border border-[#222] p-2.5 bg-[#080808] grid grid-cols-2 gap-2 text-[#888]">
                                <div>EVENT ID: <span className="text-white font-mono">{v.event_id}</span></div>
                                <div>DECISION SCORE: <span className="text-[#FF2A2A] font-mono">{v.decision_score}</span></div>
                                <div>MISSING RATIO: <span className="text-white font-mono">{(v.missing_ratio * 100).toFixed(0)}%</span></div>
                                <div>FRAMES OBSERVED: <span className="text-white font-mono">{v.observable_frames}</span></div>
                              </div>
                              <div className="border border-[#222] p-2 bg-[#080808] text-[#AAA] italic">
                                "{v.message}"
                              </div>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
