export type Accent = 'red' | 'cyan' | 'yellow';

export type SceneKind =
  | 'overview'
  | 'parallel'
  | 'tokens'
  | 'positions'
  | 'qkv'
  | 'matrix'
  | 'heads'
  | 'block'
  | 'training'
  | 'mask'
  | 'cache'
  | 'outro';

export type EpisodeScene = {
  kind: SceneKind;
  eyebrow: string;
  title: string;
  caption: string;
  weight: number;
};

export type Episode = {
  id: string;
  number: number;
  title: string;
  shortTitle: string;
  accent: Accent;
  audio: string;
  narration: string;
  /** Exact narration sentence intervals in seconds, generated with the audio. */
  narrationTimings?: number[];
  scenes: EpisodeScene[];
};
