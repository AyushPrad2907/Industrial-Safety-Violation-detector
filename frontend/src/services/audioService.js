/**
 * Audio synthesis helper using Web Audio API to create a crisp, reliable
 * industrial alarm chime without external MP3 asset dependency.
 */
let audioCtx = null;

export function playAlertSound(muted = false) {
  if (muted) return;
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;
    if (!audioCtx) {
      audioCtx = new AudioContext();
    }
    if (audioCtx.state === 'suspended') {
      audioCtx.resume();
    }

    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();

    osc.type = 'sawtooth';
    // Frequency sequence: high alert double beep
    osc.frequency.setValueAtTime(880, audioCtx.currentTime); // A5
    osc.frequency.setValueAtTime(1174.66, audioCtx.currentTime + 0.08); // D6
    osc.frequency.setValueAtTime(880, audioCtx.currentTime + 0.16);

    gain.gain.setValueAtTime(0.18, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.35);

    osc.connect(gain);
    gain.connect(audioCtx.destination);

    osc.start();
    osc.stop(audioCtx.currentTime + 0.36);
  } catch (err) {
    console.warn('Audio playback error (browser policy):', err);
  }
}

/**
 * Browser Notification Helper
 */
export async function requestNotificationPermission() {
  if (!('Notification' in window)) {
    return 'unsupported';
  }
  if (Notification.permission === 'granted') {
    return 'granted';
  }
  if (Notification.permission !== 'denied') {
    const perm = await Notification.requestPermission();
    return perm;
  }
  return Notification.permission;
}

export function showBrowserNotification(title, options = {}) {
  if (!('Notification' in window) || Notification.permission !== 'granted') {
    return;
  }
  try {
    new Notification(title, {
      icon: '/vite.svg',
      badge: '/vite.svg',
      ...options
    });
  } catch (e) {
    console.warn('Browser notification error:', e);
  }
}
