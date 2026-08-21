import React from 'react';
import {getAudioDurationInSeconds} from '@remotion/media-utils';
import {Composition, staticFile, type CalculateMetadataFunction} from 'remotion';
import {episodes} from './content';
import {TransformerEpisode, type TransformerEpisodeProps} from './TransformerEpisode';
import {
  TransformerEditorialEpisode,
  type TransformerEditorialEpisodeProps,
} from './TransformerEditorialEpisode';
import {
  TransformerBeginnerLesson,
  type TransformerBeginnerLessonProps,
} from './TransformerBeginnerLesson';
import {
  TransformerBeginnerLessonV2,
  type TransformerBeginnerLessonV2Props,
} from './TransformerBeginnerLessonV2';

export const FPS = 30;

const calculateEpisodeMetadata: CalculateMetadataFunction<TransformerEpisodeProps> = async ({
  props,
}) => {
  const audioDuration = await getAudioDurationInSeconds(staticFile(props.episode.audio));

  return {
    durationInFrames: Math.max(FPS, Math.ceil(audioDuration * FPS)),
    props,
  };
};

const calculateEditorialMetadata: CalculateMetadataFunction<TransformerEditorialEpisodeProps> = async ({
  props,
}) => {
  const audioDuration = await getAudioDurationInSeconds(staticFile(props.episode.audio));

  return {
    durationInFrames: Math.max(FPS, Math.ceil(audioDuration * FPS)),
    props,
  };
};

const calculateBeginnerLessonMetadata: CalculateMetadataFunction<TransformerBeginnerLessonProps> = async ({
  props,
}) => {
  const audioDuration = await getAudioDurationInSeconds(staticFile(props.audio));

  return {
    durationInFrames: Math.max(FPS, Math.ceil(audioDuration * FPS)),
    props,
  };
};

const calculateBeginnerLessonV2Metadata: CalculateMetadataFunction<TransformerBeginnerLessonV2Props> = async ({
  props,
}) => {
  const audioDuration = await getAudioDurationInSeconds(staticFile(props.audio));

  return {
    durationInFrames: Math.max(FPS, Math.ceil(audioDuration * FPS)),
    props,
  };
};

export const RemotionRoot: React.FC = () => {
  return (
    <>
      {episodes.map((episode) => (
        <Composition
          key={episode.id}
          id={episode.id}
          component={TransformerEpisode}
          durationInFrames={FPS * 90}
          fps={FPS}
          width={1920}
          height={1080}
          defaultProps={{episode}}
          calculateMetadata={calculateEpisodeMetadata}
        />
      ))}
      <Composition
        id="Transformer-01-Editorial"
        component={TransformerEditorialEpisode}
        durationInFrames={FPS * 90}
        fps={FPS}
        width={1920}
        height={1080}
        defaultProps={{episode: episodes[0]}}
        calculateMetadata={calculateEditorialMetadata}
      />
      <Composition
        id="Transformer-01-Editorial-V2"
        component={TransformerEditorialEpisode}
        durationInFrames={FPS * 90}
        fps={FPS}
        width={1920}
        height={1080}
        defaultProps={{episode: episodes[0]}}
        calculateMetadata={calculateEditorialMetadata}
      />
      <Composition
        id="Transformer-01-Beginner-10min"
        component={TransformerBeginnerLesson}
        durationInFrames={FPS * 620}
        fps={FPS}
        width={1920}
        height={1080}
        defaultProps={{audio: 'audio/transformer-beginner-10min.neural.mp3'}}
        calculateMetadata={calculateBeginnerLessonMetadata}
      />
      <Composition
        id="Transformer-01-Beginner-10min-V2"
        component={TransformerBeginnerLessonV2}
        durationInFrames={FPS * 600}
        fps={FPS}
        width={1920}
        height={1080}
        defaultProps={{audio: 'audio/transformer-beginner-10min-v2.neural.mp3'}}
        calculateMetadata={calculateBeginnerLessonV2Metadata}
      />
      <Composition
        id="Transformer-01-Beginner-Terms-V3"
        component={TransformerBeginnerLessonV2}
        durationInFrames={FPS * 800}
        fps={FPS}
        width={1920}
        height={1080}
        defaultProps={{
          audio: 'audio/transformer-beginner-10min-v3.neural.mp3',
          timingVersion: 'v3',
          explainTerms: true,
        }}
        calculateMetadata={calculateBeginnerLessonV2Metadata}
      />
    </>
  );
};
