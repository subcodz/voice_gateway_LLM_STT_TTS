export function concat(parts: Uint8Array[]): Uint8Array {
  const total = parts.reduce((n, p) => n + p.length, 0);
  const out = new Uint8Array(total);
  let off = 0;
  for (const p of parts) {
    out.set(p, off);
    off += p.length;
  }
  return out;
}

/** Port of app/audio.py fix_wav_header: rewrites the 0xFFFFFFFF streaming placeholders. */
export function fixWav(u8: Uint8Array): Uint8Array {
  const tag = (o: number) => String.fromCharCode(u8[o], u8[o + 1], u8[o + 2], u8[o + 3]);
  if (u8.length < 12 || tag(0) !== "RIFF" || tag(8) !== "WAVE") return u8;
  const out = u8.slice();
  const dv = new DataView(out.buffer);
  let pos = 12;
  while (pos + 8 <= out.length) {
    const id = String.fromCharCode(out[pos], out[pos + 1], out[pos + 2], out[pos + 3]);
    const size = dv.getUint32(pos + 4, true);
    if (id === "data") {
      dv.setUint32(4, out.length - 8, true);
      dv.setUint32(pos + 4, out.length - (pos + 8), true);
      return out;
    }
    pos += 8 + size + (size & 1);
  }
  return out;
}

export class AudioQueuePlayer {
  private audio: HTMLAudioElement | null = null;
  private queue: string[] = [];
  private playing: boolean = false;
  private lastUrl: string | null = null;

  constructor() {
    if (typeof Audio !== "undefined") {
      this.audio = new Audio();
      this.audio.onended = () => this.next();
    }
  }

  enqueue(u8: Uint8Array) {
    const url = URL.createObjectURL(new Blob([u8 as BlobPart], { type: "audio/wav" }));
    this.queue.push(url);
    if (!this.playing) this.next();
  }

  next() {
    if (this.lastUrl) {
      URL.revokeObjectURL(this.lastUrl);
      this.lastUrl = null;
    }
    const url = this.queue.shift();
    if (!url || !this.audio) {
      this.playing = false;
      return;
    }
    this.playing = true;
    this.lastUrl = url;
    this.audio.src = url;
    this.audio.play().catch(() => {
      this.playing = false;
    });
  }

  stop() {
    if (this.audio) this.audio.pause();
    this.queue = [];
    this.playing = false;
  }

  replay(clips: (Uint8Array | null)[]) {
    this.stop();
    clips.forEach((c) => c && this.enqueue(c));
  }
}

