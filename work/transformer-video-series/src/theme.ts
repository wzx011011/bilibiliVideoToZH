import type {Accent} from './types';

export const colors = {
  background: '#0a0a0a',
  surface: '#151515',
  surfaceRaised: '#202020',
  text: '#f5f5f2',
  muted: '#a7a7a1',
  line: '#353535',
  red: '#ff4b4b',
  cyan: '#39d4da',
  yellow: '#f5c84c',
};

export const accentColor = (accent: Accent) => colors[accent];

export const fontFamily =
  'Inter, "Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif';
