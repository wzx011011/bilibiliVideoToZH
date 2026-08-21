import React from 'react';
import {
  AbsoluteFill,
  Audio,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import type {Episode} from './types';
import {SceneVisual} from './components/SceneVisual';
import {accentColor, colors, fontFamily} from './theme';

export type TransformerEpisodeProps = {
  episode: Episode;
};

const splitNarration = (narration: string) =>
  narration.match(/[^。！？!?]+[。！？!?]?/g)?.map((sentence) => sentence.trim()).filter(Boolean) ?? [narration];

const NarrationSubtitles: React.FC<{episode: Episode}> = ({episode}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const sentences = splitNarration(episode.narration);
  const weights = sentences.map((sentence) => Math.max(8, [...sentence].length));
  const totalWeight = weights.reduce((sum, weight) => sum + weight, 0);
  const playhead = (frame / Math.max(1, durationInFrames - 1)) * totalWeight;

  let cursor = 0;
  let activeIndex = sentences.length - 1;
  for (let index = 0; index < sentences.length; index += 1) {
    cursor += weights[index];
    if (playhead < cursor) {
      activeIndex = index;
      break;
    }
  }

  const accent = accentColor(episode.accent);

  return (
    <div
      style={{
        position: 'absolute',
        left: 250,
        right: 250,
        bottom: 64,
        minHeight: 82,
        padding: '13px 30px',
        borderLeft: `5px solid ${accent}`,
        background: 'rgba(10, 10, 10, 0.94)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: colors.text,
        fontFamily,
        fontSize: 30,
        fontWeight: 650,
        lineHeight: 1.45,
        textAlign: 'center',
      }}
    >
      {sentences[activeIndex]}
    </div>
  );
};

const EpisodeChrome: React.FC<{episode: Episode}> = ({episode}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const progress = interpolate(frame, [0, durationInFrames - 1], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const accent = accentColor(episode.accent);

  return (
    <>
      <div
        style={{
          position: 'absolute',
          top: 44,
          left: 64,
          right: 64,
          height: 44,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          color: colors.muted,
          fontFamily,
          fontSize: 22,
        }}
      >
        <div style={{display: 'flex', alignItems: 'center', gap: 16}}>
          <span style={{color: accent, fontWeight: 800}}>TRANSFORMER</span>
          <span>技术入门系列</span>
        </div>
        <span>EP.{String(episode.number).padStart(2, '0')}</span>
      </div>
      <div
        style={{
          position: 'absolute',
          left: 64,
          right: 64,
          bottom: 32,
          height: 4,
          background: colors.line,
        }}
      >
        <div style={{height: '100%', width: `${progress * 100}%`, background: accent}} />
      </div>
    </>
  );
};

export const TransformerEpisode: React.FC<TransformerEpisodeProps> = ({episode}) => {
  const {durationInFrames} = useVideoConfig();
  const totalWeight = episode.scenes.reduce((sum, scene) => sum + scene.weight, 0);
  let cursor = 0;

  return (
    <AbsoluteFill style={{background: colors.background, color: colors.text, fontFamily}}>
      <Audio src={staticFile(episode.audio)} />
      {episode.scenes.map((scene, index) => {
        const isLast = index === episode.scenes.length - 1;
        const duration = isLast
          ? durationInFrames - cursor
          : Math.round((scene.weight / totalWeight) * durationInFrames);
        const from = cursor;
        cursor += duration;
        return (
          <Sequence key={`${episode.id}-${scene.kind}-${index}`} from={from} durationInFrames={duration}>
            <SceneVisual
              episode={episode}
              scene={scene}
              sceneIndex={index}
              sceneCount={episode.scenes.length}
            />
          </Sequence>
        );
      })}
      <NarrationSubtitles episode={episode} />
      <EpisodeChrome episode={episode} />
    </AbsoluteFill>
  );
};
