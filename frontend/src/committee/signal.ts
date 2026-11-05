// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Console signal tone (auto-closed vote): two short sine tones via Web
 *  Audio. Browsers block audio before a user gesture, so the console calls
 *  `primeSignal()` on its first click. */
const STORAGE_KEY = "abstimmbar.signal";

let context: AudioContext | null = null;

function audioContext(): AudioContext | null {
  if (context) return context;
  try {
    if (typeof window === "undefined" || typeof window.AudioContext === "undefined") return null;
    context = new window.AudioContext();
  } catch {
    context = null;
  }
  return context;
}

/** Create/resume the audio context; call from a user gesture. */
export function primeSignal(): void {
  try {
    const ctx = audioContext();
    if (ctx && ctx.state === "suspended") void ctx.resume().catch(() => undefined);
  } catch {
    /* audio unavailable */
  }
}

export function readSignalEnabled(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) !== "0";
  } catch {
    return true;
  }
}

export function writeSignalEnabled(value: boolean): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, value ? "1" : "0");
  } catch {
    /* storage unavailable: the choice just isn't remembered */
  }
}

/** Play two short tones; silent when audio is unavailable or blocked. */
export function playSignal(): void {
  try {
    const ctx = audioContext();
    if (!ctx) return;
    const play = () => {
      const start = ctx.currentTime;
      [660, 880].forEach((frequency, index) => {
        const at = start + index * 0.18;
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = "sine";
        osc.frequency.value = frequency;
        gain.gain.setValueAtTime(0.2, at);
        gain.gain.exponentialRampToValueAtTime(0.001, at + 0.15);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(at);
        osc.stop(at + 0.15);
      });
    };
    if (ctx.state === "suspended") ctx.resume().then(play, () => undefined);
    else play();
  } catch {
    /* audio unavailable */
  }
}
