import React, { useState, useEffect, useCallback, useRef } from 'react';

import {
  fetchHealth,
  fetchSystemStatus,
  fetchStats,
  fetchWorkers,
  fetchViolations,
  startMonitoring,
  stopMonitoring,
  resetSession
} from './services/api';
import {
  playAlertSound,
  requestNotificationPermission,
  showBrowserNotification
} from './services/audioService';
import { useWebSocketMonitor } from './hooks/useWebSocketMonitor';
import { WorkerCard } from './components/WorkerCard';
import { ViolationAlertBanner } from './components/ViolationAlertBanner';
import { ViolationHistoryTable } from './components/ViolationHistoryTable';

export default function App() {
  const [activeTab, setActiveTab] = useState('monitoring'); // monitoring | history | telemetry

  const [stats, setStats] = useState({
    fps: 0,
    frame_index: 0,
    resolution: '0x0',
    latency_ms: 0,
    active_workers: 0,
    total_violations: 0,
    critical_violations: 0,
    pipeline_state: 'IDLE'
  });

  const [systemStatus, setSystemStatus] = useState({
    ai_pipeline: 'STOPPED',
    websocket: 'DISCONNECTED',
    database: 'AVAILABLE',
    camera_video: 'STOPPED',
    telegram: 'DISABLED'
  });

  const [workers, setWorkers] = useState([]);
  const [violations, setViolations] = useState([]);
  const [loadingViolations, setLoadingViolations] = useState(false);

  const [isMuted, setIsMuted] = useState(false);
  const [notificationsEnabled, setNotificationsEnabled] = useState(false);

  const [activeAlerts, setActiveAlerts] = useState([]);
  const seenEventIdsRef = useRef(new Set());

  // WebSocket event listeners
  const handleWebSocketViolation = useCallback((violationData) => {
    const eventId = violationData.event_id;
    if (seenEventIdsRef.current.has(eventId)) return;
    seenEventIdsRef.current.add(eventId);

    playAlertSound(isMuted);

    if (notificationsEnabled) {
      showBrowserNotification(`[VIOLATION: ${violationData.severity}]`, {
        body: `Worker #${violationData.track_id}: ${violationData.violation_type}`
      });
    }

    setActiveAlerts((prev) => [violationData, ...prev.slice(0, 3)]);
    setViolations((prev) => [violationData, ...prev]);
    setStats((prev) => ({
      ...prev,
      total_violations: prev.total_violations + 1,
      critical_violations: violationData.severity === 'CRITICAL' ? prev.critical_violations + 1 : prev.critical_violations
    }));
  }, [isMuted, notificationsEnabled]);

  const handleWebSocketUpdate = useCallback((updateData) => {
    setStats((prev) => ({
      ...prev,
      fps: updateData.fps,
      frame_index: updateData.frame_index,
      latency_ms: updateData.latency_ms,
      active_workers: updateData.active_workers
    }));
    if (updateData.workers) setWorkers(updateData.workers);
  }, []);

  const { isConnected: wsConnected } = useWebSocketMonitor({
    onViolation: handleWebSocketViolation,
    onUpdate: handleWebSocketUpdate
  });

  const loadData = async () => {
    setLoadingViolations(true);
    try {
      const [sData, statData, vData] = await Promise.all([
        fetchSystemStatus().catch(() => null),
        fetchStats().catch(() => null),
        fetchViolations().catch(() => ({ violations: [] }))
      ]);
      if (sData) setSystemStatus(sData);
      if (statData) setStats(statData);
      if (vData && vData.violations) {
        setViolations(vData.violations);
        vData.violations.forEach((v) => seenEventIdsRef.current.add(v.event_id));
      }
    } catch (e) {
      console.warn('Sync failed:', e);
    } finally {
      setLoadingViolations(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const [wList, st] = await Promise.all([fetchWorkers(), fetchStats()]);
        if (wList && wList.length > 0) setWorkers(wList);
        if (st) setStats(st);
      } catch (e) {
        // quiet
      }
    }, 2500);
    return () => clearInterval(interval);
  }, []);

  const handleStart = async () => {
    try {
      await startMonitoring({ source_type: 'sample' });
      setStats((prev) => ({ ...prev, pipeline_state: 'RUNNING' }));
    } catch (e) {
      alert('Start failed: ' + e.message);
    }
  };

  const handleStop = async () => {
    try {
      await stopMonitoring();
      setStats((prev) => ({ ...prev, pipeline_state: 'STOPPED' }));
    } catch (e) {
      alert('Stop failed: ' + e.message);
    }
  };

  const handleResetSession = async () => {
    if (!window.confirm('RESET LIVE SESSION? Database records and evidence remain safe.')) return;
    try {
      const res = await resetSession();
      setWorkers([]);
      setStats((prev) => ({ ...prev, fps: 0, frame_index: 0, active_workers: 0 }));
      alert(`Session cleared. Preserved ${res.preserved_records} database records.`);
    } catch (e) {
      alert('Reset failed: ' + e.message);
    }
  };

  const toggleNotifications = async () => {
    if (!notificationsEnabled) {
      const p = await requestNotificationPermission();
      if (p === 'granted') setNotificationsEnabled(true);
      else alert('Browser denied notifications.');
    } else {
      setNotificationsEnabled(false);
    }
  };

  const isRunning = stats.pipeline_state === 'RUNNING';

  return (
    <div className="min-h-screen bg-[#0A0A0A] text-[#E5E5E5] font-mono selection:bg-[#FF2A2A] selection:text-black">
      <ViolationAlertBanner
        alerts={activeAlerts}
        onDismiss={(id) => setActiveAlerts((prev) => prev.filter((a) => a.event_id !== id))}
      />

      {/* Top Header Terminal Bar */}
      <header className="border-b-2 border-[#262626] bg-[#050505] px-4 py-2 flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-3.5 h-3.5 bg-[#FF2A2A] animate-pulse"></div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-white font-black text-sm tracking-widest uppercase">
                SAFETY-DETECTOR // OPS-CONSOLE
              </span>
              <span className="text-[10px] bg-[#1A1A1A] border border-[#333] px-1.5 text-[#888]">
                v8.2.0
              </span>
            </div>
            <div className="text-[10px] text-[#666] tracking-wider uppercase">
              HIGH-CONFIDENCE PPE TELEMETRY &amp; TEMPORAL VERIFICATION
            </div>
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-2 text-xs">
          <button
            onClick={() => setIsMuted(!isMuted)}
            className={`px-2 py-1 border text-[11px] font-bold uppercase tracking-wider transition-colors ${
              isMuted ? 'border-[#333] bg-[#111] text-[#666]' : 'border-[#FF2A2A] bg-[#FF2A2A]/10 text-[#FF2A2A]'
            }`}
          >
            {isMuted ? '[ AUDIO: MUTED ]' : '[ AUDIO: LIVE ]'}
          </button>

          <button
            onClick={toggleNotifications}
            className={`px-2 py-1 border text-[11px] font-bold uppercase tracking-wider transition-colors ${
              notificationsEnabled ? 'border-[#00FF66] bg-[#00FF66]/10 text-[#00FF66]' : 'border-[#333] bg-[#111] text-[#666]'
            }`}
          >
            {notificationsEnabled ? '[ NOTIFY: ON ]' : '[ NOTIFY: OFF ]'}
          </button>

          {!isRunning ? (
            <button
              onClick={handleStart}
              className="px-3 py-1 bg-[#00FF66] text-black font-black uppercase tracking-wider hover:bg-[#00E55B] transition-colors"
            >
              [▶ START INFERENCE]
            </button>
          ) : (
            <button
              onClick={handleStop}
              className="px-3 py-1 bg-[#FF2A2A] text-black font-black uppercase tracking-wider hover:bg-[#E51E1E] transition-colors"
            >
              [⏹ STOP INFERENCE]
            </button>
          )}

          <button
            onClick={handleResetSession}
            className="px-2 py-1 border border-[#333] bg-[#141414] text-[#AAA] hover:text-white uppercase tracking-wider text-[11px]"
            title="Reset active tracks while preserving SQLite records"
          >
            RESET
          </button>
        </div>
      </header>

      {/* Industrial Telemetry Grid */}
      <section className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 border-b border-[#262626] bg-[#080808]">
        <div className="border-r border-[#262626] p-3">
          <div className="text-[10px] text-[#666] tracking-wider uppercase">ACTIVE WORKERS</div>
          <div className="text-xl font-bold text-white mt-0.5">{stats.active_workers}</div>
        </div>

        <div className="border-r border-[#262626] p-3">
          <div className="text-[10px] text-[#666] tracking-wider uppercase">CONFIRMED VIOLATIONS</div>
          <div className="text-xl font-bold text-[#EAB308] mt-0.5">{stats.total_violations}</div>
        </div>

        <div className="border-r border-[#262626] p-3">
          <div className="text-[10px] text-[#666] tracking-wider uppercase">CRITICAL SEVERITY</div>
          <div className="text-xl font-bold text-[#FF2A2A] mt-0.5">{stats.critical_violations}</div>
        </div>

        <div className="border-r border-[#262626] p-3">
          <div className="text-[10px] text-[#666] tracking-wider uppercase">SYSTEM FPS</div>
          <div className="text-xl font-bold text-[#00FF66] mt-0.5">{stats.fps.toFixed(1)}</div>
        </div>

        <div className="border-r border-[#262626] p-3">
          <div className="text-[10px] text-[#666] tracking-wider uppercase">CURRENT FRAME</div>
          <div className="text-xl font-bold text-[#AAA] mt-0.5">#{stats.frame_index}</div>
        </div>

        <div className="p-3">
          <div className="text-[10px] text-[#666] tracking-wider uppercase">LATENCY (MS)</div>
          <div className="text-xl font-bold text-[#888] mt-0.5">{stats.latency_ms.toFixed(1)}</div>
        </div>
      </section>

      {/* Navigation Sub-Nav Tabs */}
      <nav className="flex border-b border-[#262626] bg-[#050505] text-xs">
        <button
          onClick={() => setActiveTab('monitoring')}
          className={`py-2 px-4 uppercase tracking-wider font-bold transition-colors ${
            activeTab === 'monitoring'
              ? 'bg-[#141414] text-white border-b-2 border-[#FF2A2A]'
              : 'text-[#666] hover:text-[#CCC]'
          }`}
        >
          [ 01 // LIVE INFERENCE &amp; WORKERS ]
        </button>

        <button
          onClick={() => setActiveTab('history')}
          className={`py-2 px-4 uppercase tracking-wider font-bold transition-colors ${
            activeTab === 'history'
              ? 'bg-[#141414] text-white border-b-2 border-[#FF2A2A]'
              : 'text-[#666] hover:text-[#CCC]'
          }`}
        >
          [ 02 // VIOLATION ARCHIVE ({violations.length}) ]
        </button>

        <button
          onClick={() => setActiveTab('telemetry')}
          className={`py-2 px-4 uppercase tracking-wider font-bold transition-colors ${
            activeTab === 'telemetry'
              ? 'bg-[#141414] text-white border-b-2 border-[#FF2A2A]'
              : 'text-[#666] hover:text-[#CCC]'
          }`}
        >
          [ 03 // DIAGNOSTICS &amp; HARDWARE ]
        </button>
      </nav>

      {/* Main Container */}
      <main className="p-4 max-w-[1600px] mx-auto">
        {activeTab === 'monitoring' && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 items-start">
            {/* Live Video Feed Column */}
            <div className="lg:col-span-8 bg-[#0D0D0D] border border-[#262626] p-3">
              <div className="flex items-center justify-between pb-2 border-b border-[#222] text-xs">
                <span className="text-white font-bold tracking-wider uppercase">
                  /// OPTICAL FEED // DETECTIONS ANNOTATED
                </span>
                <span className={`text-[10px] font-bold uppercase px-1.5 py-0.5 ${isRunning ? 'bg-[#00FF66] text-black' : 'bg-[#333] text-[#888]'}`}>
                  {isRunning ? 'FEED: ONLINE' : 'FEED: OFFLINE'}
                </span>
              </div>

              {/* Video Player */}
              <div className="mt-2.5 bg-black border border-[#222] aspect-video flex items-center justify-center overflow-hidden">
                {isRunning ? (
                  <img
                    src="/api/video/stream"
                    alt="Live Video Stream"
                    className="w-full h-full object-contain"
                  />
                ) : (
                  <div className="text-center p-8 text-[#555] space-y-2 font-mono">
                    <p className="text-sm font-bold text-[#888]">[ INFERENCE PIPELINE INACTIVE ]</p>
                    <p className="text-xs text-[#555]">Click [▶ START INFERENCE] in header to engage video stream.</p>
                  </div>
                )}
              </div>
            </div>

            {/* Tracked Workers Column */}
            <div className="lg:col-span-4 space-y-3">
              <div className="flex items-center justify-between p-2 bg-[#0D0D0D] border border-[#262626] text-xs">
                <span className="text-white font-bold tracking-wider uppercase">
                  ACTIVE WORKER MATRIX ({workers.length})
                </span>
                <span className="text-[10px] text-[#666]">TEMPORAL CONFIRMATION</span>
              </div>

              {workers.length === 0 ? (
                <div className="p-8 text-center text-[#555] border border-dashed border-[#262626] bg-[#0A0A0A] text-xs">
                  [ NO WORKERS DETECTED IN SCAN SECTOR ]
                </div>
              ) : (
                <div className="space-y-2.5 max-h-[640px] overflow-y-auto pr-1">
                  {workers.map((w) => (
                    <WorkerCard key={w.track_id} worker={w} />
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'history' && (
          <ViolationHistoryTable
            violations={violations}
            onRefresh={loadData}
            loading={loadingViolations}
          />
        )}

        {activeTab === 'telemetry' && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* System Health */}
            <div className="bg-[#0D0D0D] border border-[#262626] p-4 text-xs space-y-3">
              <div className="text-white font-bold uppercase tracking-wider pb-2 border-b border-[#222]">
                /// HARDWARE &amp; SERVICE STATUS
              </div>
              <div className="space-y-2">
                <div className="flex justify-between py-1.5 px-2 bg-[#121212] border border-[#1F1F1F]">
                  <span className="text-[#888]">AI PIPELINE ENGINE</span>
                  <span className="text-[#00FF66] font-bold">[{systemStatus.ai_pipeline}]</span>
                </div>
                <div className="flex justify-between py-1.5 px-2 bg-[#121212] border border-[#1F1F1F]">
                  <span className="text-[#888]">WEBSOCKET REALTIME CHANNEL</span>
                  <span className={`font-bold ${wsConnected ? 'text-[#00FF66]' : 'text-[#FF2A2A]'}`}>
                    [{wsConnected ? 'ONLINE' : 'OFFLINE'}]
                  </span>
                </div>
                <div className="flex justify-between py-1.5 px-2 bg-[#121212] border border-[#1F1F1F]">
                  <span className="text-[#888]">SQLITE AUDIT STORE</span>
                  <span className="text-[#00FF66] font-bold">[{systemStatus.database}]</span>
                </div>
                <div className="flex justify-between py-1.5 px-2 bg-[#121212] border border-[#1F1F1F]">
                  <span className="text-[#888]">TELEGRAM EMERGENCY DISPATCH</span>
                  <span className="text-[#EAB308] font-bold">[{systemStatus.telegram}]</span>
                </div>
              </div>
            </div>

            {/* Pipeline Architecture Spec */}
            <div className="bg-[#0D0D0D] border border-[#262626] p-4 text-xs space-y-2 text-[#888]">
              <div className="text-white font-bold uppercase tracking-wider pb-2 border-b border-[#222]">
                /// PIPELINE SPECIFICATION
              </div>
              <p>STAGED INFERENCE SEQUENCE:</p>
              <div className="p-3 bg-[#080808] border border-[#1F1F1F] font-mono text-[11px] space-y-1 text-[#AAA]">
                <div>01. YOLOv8n Bounding Box Localization</div>
                <div>02. ByteTrack Persistent Kalman Filter Association</div>
                <div>03. Specialized PPE Equipment Classifiers</div>
                <div>04. Bipartite Geometry Intersection Matcher</div>
                <div>05. Sliding-Window Anti-Flicker Debouncing</div>
                <div>06. High-Res Forensic Crop &amp; SQLite Ingestion</div>
                <div>07. Multi-Client MJPEG Stream + WebSocket Broadcast</div>
              </div>
              <p className="text-[10px] text-[#555] pt-2">
                ACADEMIC DEMO INTERFACE: <code className="text-white">python -m streamlit run app.py</code>
              </p>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
