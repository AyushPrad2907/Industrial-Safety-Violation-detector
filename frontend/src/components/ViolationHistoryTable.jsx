import React, { useState } from 'react';
import { Download, RefreshCw, Filter, Image, AlertCircle, CheckCircle2, ChevronDown, ChevronUp } from 'lucide-react';
import { getCsvExportUrl, getEvidenceUrl } from '../services/api';

export function ViolationHistoryTable({ violations, onRefresh, loading }) {
  const [selectedSeverity, setSelectedSeverity] = useState('All');
  const [selectedType, setSelectedType] = useState('All');
  const [selectedWorker, setSelectedWorker] = useState('All');
  const [expandedRow, setExpandedRow] = useState(null);

  // Derive unique workers from current violation set
  const workerOptions = ['All', ...new Set(violations.map((v) => String(v.track_id)))].sort();
  const typeOptions = ['All', 'Missing Helmet', 'Missing Vest', 'Missing Gloves', 'Missing Boots', 'Missing Goggles'];
  const severityOptions = ['All', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];

  // Client-side filtering for immediate snappy responsiveness
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
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-xl">
      {/* Table Header & Controls */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-slate-800">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            📋 Confirmed Violation History
          </h2>
          <p className="text-sm text-slate-400">
            SQLite persisted safety violations from Phase 6 temporal engine
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={onRefresh}
            disabled={loading}
            className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-sm font-medium transition-colors border border-slate-700"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <a
            href={exportUrl}
            download="violation_history.csv"
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-semibold transition-colors shadow-lg shadow-indigo-600/20"
          >
            <Download className="w-4 h-4" />
            Download CSV
          </a>
        </div>
      </div>

      {/* Filter Toolbar */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 py-4 bg-slate-950/40 px-4 rounded-lg my-4 border border-slate-800/60">
        <div>
          <label className="block text-xs font-semibold text-slate-400 mb-1.5 flex items-center gap-1">
            <Filter className="w-3.5 h-3.5" /> Severity Filter
          </label>
          <select
            value={selectedSeverity}
            onChange={(e) => setSelectedSeverity(e.target.value)}
            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
          >
            {severityOptions.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs font-semibold text-slate-400 mb-1.5 flex items-center gap-1">
            <Filter className="w-3.5 h-3.5" /> Violation Type
          </label>
          <select
            value={selectedType}
            onChange={(e) => setSelectedType(e.target.value)}
            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
          >
            {typeOptions.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs font-semibold text-slate-400 mb-1.5 flex items-center gap-1">
            <Filter className="w-3.5 h-3.5" /> Worker ID
          </label>
          <select
            value={selectedWorker}
            onChange={(e) => setSelectedWorker(e.target.value)}
            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
          >
            {workerOptions.map((w) => (
              <option key={w} value={w}>{w === 'All' ? 'All Workers' : `Worker #${w}`}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="text-xs text-slate-400 mb-3 px-1">
        Showing <strong className="text-white">{filteredViolations.length}</strong> of{' '}
        <strong className="text-white">{violations.length}</strong> recorded violations
      </div>

      {/* Violations Table */}
      {filteredViolations.length === 0 ? (
        <div className="text-center py-12 text-slate-500 bg-slate-950/20 rounded-xl border border-dashed border-slate-800">
          <CheckCircle2 className="w-12 h-12 text-emerald-500/50 mx-auto mb-3" />
          <p className="text-base font-medium text-slate-300">No violations match the selected filters.</p>
          <p className="text-xs text-slate-500 mt-1">Adjust filters or start monitoring to observe live violations.</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-800">
          <table className="w-full text-left text-sm text-slate-300">
            <thead className="bg-slate-950 text-xs uppercase text-slate-400 border-b border-slate-800 font-semibold">
              <tr>
                <th className="px-4 py-3">Timestamp</th>
                <th className="px-4 py-3">Worker ID</th>
                <th className="px-4 py-3">Violation</th>
                <th className="px-4 py-3">Severity</th>
                <th className="px-4 py-3">Score</th>
                <th className="px-4 py-3">Zone</th>
                <th className="px-4 py-3 text-right">Evidence</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-normal">
              {filteredViolations.map((v) => {
                const isCrit = v.severity === 'CRITICAL';
                const isHigh = v.severity === 'HIGH';
                const sevBadge = isCrit
                  ? 'bg-rose-500/20 text-rose-300 border-rose-500/30'
                  : isHigh
                  ? 'bg-amber-500/20 text-amber-300 border-amber-500/30'
                  : 'bg-yellow-500/20 text-yellow-300 border-yellow-500/30';

                const isExpanded = expandedRow === v.event_id;

                return (
                  <React.Fragment key={v.event_id}>
                    <tr className="hover:bg-slate-800/40 transition-colors">
                      <td className="px-4 py-3 text-xs font-mono text-slate-400">{v.timestamp}</td>
                      <td className="px-4 py-3 font-semibold text-slate-100">Worker #{v.track_id}</td>
                      <td className="px-4 py-3 font-medium text-slate-200">{v.violation_type}</td>
                      <td className="px-4 py-3">
                        <span className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-bold border ${sevBadge}`}>
                          {v.severity}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs font-mono">{v.decision_score}</td>
                      <td className="px-4 py-3 text-xs">
                        {v.is_zone_violation ? (
                          <span className="text-rose-400 font-bold">YES</span>
                        ) : (
                          <span className="text-slate-500">NO</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          onClick={() => toggleExpand(v.event_id)}
                          className="inline-flex items-center gap-1.5 px-3 py-1 rounded bg-slate-800 hover:bg-slate-700 text-xs font-medium text-indigo-300 transition-colors border border-slate-700"
                        >
                          <Image className="w-3.5 h-3.5" />
                          <span>Preview</span>
                          {isExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                        </button>
                      </td>
                    </tr>

                    {/* Expandable Evidence Row */}
                    {isExpanded && (
                      <tr className="bg-slate-950/60 border-t border-b border-indigo-950/50">
                        <td colSpan={7} className="px-6 py-4">
                          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-start">
                            {/* Evidence Image */}
                            <div className="md:col-span-1 rounded-xl overflow-hidden border border-slate-700/80 bg-black/60 shadow-lg">
                              <img
                                src={getEvidenceUrl(v.event_id)}
                                alt={`Evidence for ${v.event_id}`}
                                className="w-full h-auto object-cover"
                                onError={(e) => {
                                  e.target.style.display = 'none';
                                  e.target.nextSibling.style.display = 'flex';
                                }}
                              />
                              <div
                                style={{ display: 'none' }}
                                className="p-8 text-center flex-col items-center justify-center text-amber-400 text-xs gap-2"
                              >
                                <AlertCircle className="w-8 h-8 text-amber-500 mx-auto" />
                                <span>Evidence file unavailable.</span>
                              </div>
                            </div>

                            {/* Evidence Metadata Details */}
                            <div className="md:col-span-2 space-y-2 text-xs">
                              <div className="p-3 bg-slate-900 rounded-lg border border-slate-800 grid grid-cols-2 gap-2">
                                <div>
                                  <span className="text-slate-500">Event ID:</span>
                                  <p className="font-mono text-slate-200">{v.event_id}</p>
                                </div>
                                <div>
                                  <span className="text-slate-500">Decision Score:</span>
                                  <p className="font-mono text-rose-300">{v.decision_score}</p>
                                </div>
                                <div>
                                  <span className="text-slate-500">Missing Ratio:</span>
                                  <p className="font-mono text-slate-200">{(v.missing_ratio * 100).toFixed(0)}%</p>
                                </div>
                                <div>
                                  <span className="text-slate-500">Observable Frames:</span>
                                  <p className="font-mono text-slate-200">{v.observable_frames}</p>
                                </div>
                              </div>
                              <p className="text-slate-400 italic bg-slate-900/60 p-2.5 rounded border border-slate-800">
                                "{v.message}"
                              </p>
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
