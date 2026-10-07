import React, { useState, useEffect, useCallback } from 'react';
import {
  Play,
  Square,
  RotateCcw,
  Volume2,
  VolumeX,
  Bell,
  BellOff,
  Activity,
  Shield,
  Users,
  AlertTriangle,
  Radio,
  Server,
  Database,
  Tv
} from 'lucide-react';

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
  // Navigation tabs
  const [activeTab, setActiveTab] = useState('monitoring'); // monitoring | history | compliance

  // System & Telemetry states
  const [stats, setStats] = useState({
    fps: 0,
    frame_index: 0,
    resolution: '—',
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

  // Audio & Notification preferences
  const [isMuted, setIsMuted] = useState(false);
  const [notificationsEnabled, setNotificationsEnabled] = useState(false);

  // Active in-website alerts (deduplicated by event_id)
  const [activeAlerts, setActiveAlerts] = useState([]);
  const seenEventIdsRef = useRef(new Set());

  // WebSocket message handlers
  const handleWebSocketViolation = useCallback((violationData) => {
    const eventId = violationData.event_id;
    if (seenEventIdsRef.current.has(eventId)) {
      return; // Deduplicate
    }
    seenEventIdsRef.current.add(eventId);

    // 1. Play alert chime
    playAlertSound(isMuted);

    // 2. Dispatch browser notification if enabled
    if (notificationsEnabled) {
      showBrowserNotification(`🚨 ${violationData.severity} Safety Violation`, {
        body: `Worker #${violationData.track_id}: ${violationData.violation_type}`
      });
    }

    // 3. Add to prominent in-website alert banner
    setActiveAlerts((prev) => [violationData, ...prev.slice(0, 4)]);

    // 4. Update violations list and stats
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
    if (updateData.workers) {
      setWorkers(updateData.workers);
    }
  }, []);

  const { isConnected: wsConnected } = useWebSocketMonitor({
    onViolation: handleWebSocketViolation,
    onUpdate: handleWebSocketUpdate
  });

  // Initial data loading
  const loadInitialData = async () => {
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
        // Pre-populate seen set with existing event IDs to avoid re-alerting historical items
        vData.violations.forEach((v) => seenEventIdsRef.current.add(v.event_id));
      }
    } catch (err) {
      console.warn('Initial load error:', err);
    }
  };

  useEffect(() => {
    loadInitialData();
  }, []);

  // Polling fallback for workers/stats when monitoring is active
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const [wList, st] = await Promise.all([fetchWorkers(), fetchStats()]);
        if (wList && wList.length > 0) setWorkers(wList);
        if (st) setStats(st);
      } catch (e) {
        // quiet catch
      }
    }, 2000);
    return () => clearInterval(interval);
  }, []);

  const handleStart = async () => {
    try {
      await startMonitoring({ source_type: 'sample' });
      setSystemStatus((prev) => ({ ...prev, camera_video: 'RUNNING', ai_pipeline: 'CONNECTED' }));
      setStats((prev) => ({ ...prev, pipeline_state: 'RUNNING' }));
    } catch (e) {
      alert('Error starting monitoring: ' + e.message);
    }
  };

  const handleStop = async () => {
    try {
      await stopMonitoring();
      setSystemStatus((prev) => ({ ...prev, camera_video: 'STOPPED' }));
      setStats((prev) => ({ ...prev, pipeline_state: 'STOPPED' }));
    } catch (e) {
      alert('Error stopping monitoring: ' + e.message);
    }
  };

  const handleResetSession = async () => {
    if (!window.confirm('Reset live tracking state? Historical violations and evidence files will remain preserved.')) {
      return;
    }
    try {
      const res = await resetSession();
      setWorkers([]);
      setStats((prev) => ({ ...prev, fps: 0, frame_index: 0, active_workers: 0 }));
      alert(`Session cleared. Preserved ${res.preserved_records} historical database records.`);
    } catch (e) {
      alert('Error resetting session: ' + e.message);
    }
  };

  const handleDismissAlert = (eventId) => {
    setActiveAlerts((prev) => prev.filter((a) => a.event_id !== eventId));
  };

  const toggleNotifications = async () => {
    if (!notificationsEnabled) {
      const perm = await requestNotificationPermission();
      if (perm === 'granted') {
        setNotificationsEnabled(true);
      } else {
        alert('Browser notification permission was not granted.');
      }
    } else {
      setNotificationsEnabled(false);
    }
  };

  const isPipelineRunning = stats.pipeline_state === 'RUNNING';

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      {/* Real-time In-Website Violation Banner */}
      <ViolationAlertBanner alerts={activeAlerts} onDismiss={handleDismissAlert} />

      {/* Top Application Bar */}
      <header className="border-b border-slate-800 bg-slate-900/80 backdrop-blur-md sticky top-0 z-40 px-6 py-3.5 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-indigo-600/20 border border-indigo-500/30 text-indigo-400">
            <Shield className="w-6 h-6" />
          </div>
          <div>
            <h1 className="text-lg font-black tracking-wide text-white uppercase flex items-center gap-2">
              Industrial Safety Monitoring System
            </h1>
            <p className="text-xs text-slate-400">FastAPI & React Real-Time PPE Compliance & Violation Detection</p>
          </div>
        </div>

        {/* Action Controls & Toggles */}
        <div className="flex items-center gap-3">
          {/* Mute Toggle */}
          <button
            onClick={() => setIsMuted(!isMuted)}
            className={`p-2 rounded-lg border text-xs font-medium flex items-center gap-1.5 transition-colors ${
              isMuted
                ? 'bg-slate-800 border-slate-700 text-slate-400'
                : 'bg-indigo-600/20 border-indigo-500/40 text-indigo-300'
            }`}
            title={isMuted ? 'Unmute alert sound' : 'Mute alert sound'}
          >
            {isMuted ? <VolumeX className="w-4 h-4" /> : <Volume2 className="w-4 h-4" />}
            <span>{isMuted ? 'Muted' : 'Sound On'}</span>
          </button>

          {/* Browser Notifications Toggle */}
          <button
            onClick={toggleNotifications}
            className={`p-2 rounded-lg border text-xs font-medium flex items-center gap-1.5 transition-colors ${
              notificationsEnabled
                ? 'bg-emerald-600/20 border-emerald-500/40 text-emerald-300'
                : 'bg-slate-800 border-slate-700 text-slate-400'
            }`}
            title="Browser push notification permission"
          >
            {notificationsEnabled ? <Bell className="w-4 h-4" /> : <BellOff className="w-4 h-4" />}
            <span>{notificationsEnabled ? 'Notify On' : 'Notify Off'}</span>
          </button>

          {/* Pipeline Start/Stop Controls */}
          {!isPipelineRunning ? (
            <button
              onClick={handleStart}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs tracking-wide uppercase transition-colors shadow-lg shadow-emerald-600/20"
            >
              <Play className="w-4 h-4 fill-white" /> Start
            </button>
          ) : (
            <button
              onClick={handleStop}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-rose-600 hover:bg-rose-500 text-white font-semibold text-xs tracking-wide uppercase transition-colors shadow-lg shadow-rose-600/20"
            >
              <Square className="w-4 h-4 fill-white" /> Stop
            </button>
          )}

          {/* Reset Session */}
          <button
            onClick={handleResetSession}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium border border-slate-700 transition-colors"
            title="Clear live session state while keeping database history intact"
          >
            <RotateCcw className="w-4 h-4" /> Reset
          </button>
        </div>
      </header>

      {/* Primary KPI Metrics Bar */}
      <div className="bg-slate-900 border-b border-slate-800 px-6 py-4">
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
          <div className="bg-slate-950/60 p-3.5 rounded-xl border border-slate-800">
            <span className="text-xs text-slate-400 flex items-center gap-1.5">
              <Users className="w-3.5 h-3.5 text-indigo-400" /> Active Workers
            </span>
            <div className="text-2xl font-black text-white mt-1">{stats.active_workers}</div>
          </div>

          <div className="bg-slate-950/60 p-3.5 rounded-xl border border-slate-800">
            <span className="text-xs text-slate-400 flex items-center gap-1.5">
              <AlertTriangle className="w-3.5 h-3.5 text-amber-400" /> Confirmed Violations
            </span>
            <div className="text-2xl font-black text-amber-300 mt-1">{stats.total_violations}</div>
          </div>

          <div className="bg-slate-950/60 p-3.5 rounded-xl border border-slate-800">
            <span className="text-xs text-slate-400 flex items-center gap-1.5">
              <AlertTriangle className="w-3.5 h-3.5 text-rose-400" /> Critical Violations
            </span>
            <div className="text-2xl font-black text-rose-400 mt-1">{stats.critical_violations}</div>
          </div>

          <div className="bg-slate-950/60 p-3.5 rounded-xl border border-slate-800">
            <span className="text-xs text-slate-400 flex items-center gap-1.5">
              <Activity className="w-3.5 h-3.5 text-emerald-400" /> System FPS
            </span>
            <div className="text-2xl font-black text-emerald-300 mt-1">{stats.fps.toFixed(1)}</div>
          </div>

          <div className="bg-slate-950/60 p-3.5 rounded-xl border border-slate-800">
            <span className="text-xs text-slate-400 flex items-center gap-1.5">
              <Radio className="w-3.5 h-3.5 text-cyan-400" /> Current Frame
            </span>
            <div className="text-2xl font-black text-slate-200 mt-1">#{stats.frame_index}</div>
          </div>

          <div className="bg-slate-950/60 p-3.5 rounded-xl border border-slate-800">
            <span className="text-xs text-slate-400 flex items-center gap-1.5">
              <Server className="w-3.5 h-3.5 text-violet-400" /> Latency
            </span>
            <div className="text-2xl font-black text-violet-300 mt-1">{stats.latency_ms.toFixed(1)} ms</div>
          </div>
        </div>
      </div>

      {/* Navigation Sub-Tabs */}
      <div className="px-6 border-b border-slate-800 bg-slate-950 flex gap-4">
        <button
          onClick={() => setActiveTab('monitoring')}
          className={`py-3 px-2 border-b-2 text-sm font-semibold transition-colors flex items-center gap-2 ${
            activeTab === 'monitoring'
              ? 'border-indigo-500 text-indigo-400'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <Tv className="w-4 h-4" /> Live Monitoring & Workers
        </button>
        <button
          onClick={() => setActiveTab('history')}
          className={`py-3 px-2 border-b-2 text-sm font-semibold transition-colors flex items-center gap-2 ${
            activeTab === 'history'
              ? 'border-indigo-500 text-indigo-400'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <Database className="w-4 h-4" /> Violation History ({violations.length})
        </button>
        <button
          onClick={() => setActiveTab('compliance')}
          className={`py-3 px-2 border-b-2 text-sm font-semibold transition-colors flex items-center gap-2 ${
            activeTab === 'compliance'
              ? 'border-indigo-500 text-indigo-400'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <Shield className="w-4 h-4" /> System Health & Status
        </button>
      </div>

      {/* Main Tab Content */}
      <main className="flex-1 p-6 max-w-7xl mx-auto w-full">
        {activeTab === 'monitoring' && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
            {/* Left Column: Live Video Area */}
            <div className="lg:col-span-7 bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-xl">
              <div className="flex items-center justify-between pb-4 border-b border-slate-800">
                <h3 className="font-bold text-base text-white flex items-center gap-2">
                  <Tv className="w-4 h-4 text-indigo-400" />
                  Live Annotated Video Feed
                </h3>
                <span
                  className={`px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                    isPipelineRunning
                      ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                      : 'bg-slate-800 text-slate-400'
                  }`}
                >
                  {isPipelineRunning ? 'STREAM ACTIVE' : 'STREAM STANDBY'}
                </span>
              </div>

              {/* Video Streaming Container */}
              <div className="mt-4 rounded-xl overflow-hidden bg-black aspect-video flex items-center justify-center border border-slate-800 relative shadow-inner">
                {isPipelineRunning ? (
                  <img
                    src="/api/video/stream"
                    alt="Live Safety Monitoring"
                    className="w-full h-full object-contain"
                  />
                ) : (
                  <div className="text-center p-8 text-slate-500 space-y-2">
                    <Tv className="w-12 h-12 mx-auto stroke-1 text-slate-600" />
                    <p className="text-sm font-medium text-slate-400">Monitoring loop is currently stopped.</p>
                    <p className="text-xs text-slate-600">Click "START" in the top bar to initialize AI inference stream.</p>
                  </div>
                )}
              </div>
            </div>

            {/* Right Column: Active Worker Status List */}
            <div className="lg:col-span-5 space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="font-bold text-base text-white flex items-center gap-2">
                  <Users className="w-4 h-4 text-indigo-400" />
                  Active Workers ({workers.length})
                </h3>
                <span className="text-xs text-slate-400">Phase 4 & 5 Temporal Status</span>
              </div>

              {workers.length === 0 ? (
                <div className="bg-slate-900 border border-dashed border-slate-800 rounded-xl p-8 text-center text-slate-500">
                  <p className="text-sm font-medium">No active workers detected.</p>
                  <p className="text-xs text-slate-600 mt-1">Workers will populate here upon detection.</p>
                </div>
              ) : (
                <div className="space-y-3 max-h-[620px] overflow-y-auto pr-1">
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
            onRefresh={loadInitialData}
            loading={loadingViolations}
          />
        )}

        {activeTab === 'compliance' && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* System Status Panel */}
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-xl">
              <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
                <Server className="w-5 h-5 text-indigo-400" /> System Component Health
              </h3>
              <div className="space-y-3">
                <div className="flex items-center justify-between p-3 rounded-lg bg-slate-950/60 border border-slate-800/80">
                  <span className="text-sm text-slate-300 font-medium">AI Pipeline Status</span>
                  <span className="text-xs font-bold px-2.5 py-1 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                    {systemStatus.ai_pipeline}
                  </span>
                </div>
                <div className="flex items-center justify-between p-3 rounded-lg bg-slate-950/60 border border-slate-800/80">
                  <span className="text-sm text-slate-300 font-medium">WebSocket Connection</span>
                  <span className={`text-xs font-bold px-2.5 py-1 rounded-full ${wsConnected ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' : 'bg-rose-500/20 text-rose-400 border border-rose-500/30'}`}>
                    {wsConnected ? 'CONNECTED' : 'DISCONNECTED'}
                  </span>
                </div>
                <div className="flex items-center justify-between p-3 rounded-lg bg-slate-950/60 border border-slate-800/80">
                  <span className="text-sm text-slate-300 font-medium">SQLite Database</span>
                  <span className="text-xs font-bold px-2.5 py-1 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                    {systemStatus.database}
                  </span>
                </div>
                <div className="flex items-center justify-between p-3 rounded-lg bg-slate-950/60 border border-slate-800/80">
                  <span className="text-sm text-slate-300 font-medium">Camera / Video Feed</span>
                  <span className={`text-xs font-bold px-2.5 py-1 rounded-full ${isPipelineRunning ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' : 'bg-slate-800 text-slate-400'}`}>
                    {systemStatus.camera_video}
                  </span>
                </div>
                <div className="flex items-center justify-between p-3 rounded-lg bg-slate-950/60 border border-slate-800/80">
                  <span className="text-sm text-slate-300 font-medium">Telegram Alerts</span>
                  <span className="text-xs font-bold px-2.5 py-1 rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30">
                    {systemStatus.telegram}
                  </span>
                </div>
              </div>
            </div>

            {/* Architecture Card */}
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-xl flex flex-col justify-between">
              <div>
                <h3 className="text-lg font-bold text-white mb-2 flex items-center gap-2">
                  <Activity className="w-5 h-5 text-indigo-400" /> Pipeline Architecture
                </h3>
                <p className="text-xs text-slate-400 leading-relaxed">
                  Unified singleton pipeline architecture executing YOLOv8 person detection, ByteTrack tracking, PPE detection, Hungarian bipartite association, and sliding-window temporal validation.
                </p>
                <div className="mt-4 p-4 rounded-xl bg-slate-950 border border-slate-800 text-xs font-mono text-slate-300 space-y-1">
                  <p className="text-indigo-400 font-semibold">Inference Pipeline Sequence:</p>
                  <p>1. YOLOv8n Worker Detection</p>
                  <p>2. ByteTrack Multi-Worker Tracking</p>
                  <p>3. YOLOv8 PPE Equipment Detection</p>
                  <p>4. Worker ↔ PPE Spatial Association</p>
                  <p>5. Temporal Sliding-Window Engine</p>
                  <p>6. Evidence Crop & SQLite Persistence</p>
                  <p>7. Real-Time WebSocket & MJPEG Broadcast</p>
                </div>
              </div>
              <div className="mt-4 pt-4 border-t border-slate-800 text-xs text-slate-500">
                Fallback Streamlit demo UI available via: <code className="text-indigo-400">python -m streamlit run app.py</code>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
