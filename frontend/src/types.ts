export interface GuidedPrompt {
  label: string;
  text: string;
  hint: string;
}

export interface TurnSummary {
  turn: number;
  text: string;
  lang: string;
  reply: string | null;
  source: string | null;
  sim: number;
  replyReadyMs: number;
  replyAt: number | null;
  cached: ArmData;
  uncached: ArmData;
  skipped: boolean;
  summary: any;
}

export interface ArmMetrics {
  clauses: number;
  clause_hits: number;
  tts_chars: number;
  tts_calls: number;
  first_playable_ms: number;
  total_ms: number;
  first_byte_ms: number;
  unattributed_ms: number;
  noisy?: boolean;
  error?: string;
}

export interface ArmData {
  chunks: Record<number, Uint8Array[]>;
  clips: (Uint8Array | null)[];
  src: string[];
  m: ArmMetrics | null;
  firstAudioClientMs: number | null;
}

export interface SessionSnapshot {
  turns: number;
  chars_per_credit: number;
  llm: {
    calls: number;
    exact_hits: number;
    semantic_hits: number;
    intent_hits: number;
  };
  arms: {
    cached: {
      turns: number;
      timed_turns: number;
      tts_chars: number;
      tts_calls: number;
      est_credits: number;
      clauses: number;
      clause_hits: number;
      first_playable_ms: number;
      total_ms: number;
    };
    uncached: {
      turns: number;
      timed_turns: number;
      tts_chars: number;
      tts_calls: number;
      est_credits: number;
      clauses: number;
      clause_hits: number;
      first_playable_ms: number;
      total_ms: number;
    };
  };
  saved: {
    compared_turns: number;
    tts_chars: number;
    tts_calls: number;
    est_credits: number;
    first_playable_ms: number;
    total_ms: number;
    noisy_turns: number;
  };
}

