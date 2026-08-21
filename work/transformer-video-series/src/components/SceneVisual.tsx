import React from 'react';
import {
  Binary,
  Boxes,
  BrainCircuit,
  Braces,
  Database,
  Layers3,
  Network,
  Route,
  Sigma,
} from 'lucide-react';
import {interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import type {Episode, EpisodeScene} from '../types';
import {accentColor, colors, fontFamily} from '../theme';

const fade = (frame: number, duration: number) =>
  interpolate(frame, [0, 12, duration - 12, duration], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

const Token: React.FC<{text: string; color: string; active?: boolean}> = ({
  text,
  color,
  active,
}) => (
  <div
    style={{
      minWidth: 116,
      height: 72,
      padding: '0 22px',
      border: `2px solid ${active ? color : colors.line}`,
      borderRadius: 6,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      color: active ? colors.text : colors.muted,
      background: active ? colors.surfaceRaised : colors.surface,
      fontSize: 28,
      fontWeight: 700,
    }}
  >
    {text}
  </div>
);

const Line: React.FC<{
  x: number;
  y: number;
  width: number;
  rotate?: number;
  color: string;
  progress: number;
}> = ({x, y, width, rotate = 0, color, progress}) => (
  <div
    style={{
      position: 'absolute',
      left: x,
      top: y,
      width: width * progress,
      height: 3,
      transform: `rotate(${rotate}deg)`,
      transformOrigin: 'left center',
      background: color,
    }}
  />
);

const Overview: React.FC<{accent: string; progress: number}> = ({accent, progress}) => (
  <div style={{position: 'relative', width: 720, height: 430}}>
    {['输入向量', 'Self-Attention', '前馈网络', '上下文表示'].map((label, index) => (
      <div
        key={label}
        style={{
          position: 'absolute',
          left: 60 + index * 155,
          top: 150 + (index % 2) * 44,
          width: 130,
          height: 120,
          border: `2px solid ${index === 1 ? accent : colors.line}`,
          borderRadius: 6,
          background: colors.surface,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          textAlign: 'center',
          fontSize: 24,
          lineHeight: 1.35,
          transform: `translateY(${(1 - progress) * (index + 1) * 18}px)`,
          opacity: progress,
        }}
      >
        {label}
      </div>
    ))}
    {[0, 1, 2].map((index) => (
      <Line
        key={index}
        x={190 + index * 155}
        y={210 + (index % 2) * 44}
        width={34}
        rotate={index % 2 === 0 ? 36 : -36}
        color={accent}
        progress={progress}
      />
    ))}
  </div>
);

const Parallel: React.FC<{accent: string; progress: number; modern: boolean}> = ({
  accent,
  progress,
  modern,
}) => {
  const tokens = ['我', '正在', '学习', '注意力'];
  return (
    <div style={{position: 'relative', width: 760, height: 430}}>
      <div style={{display: 'flex', gap: 32, position: 'absolute', top: 170, left: 30}}>
        {tokens.map((token, index) => (
          <Token key={token} text={token} color={accent} active={modern || index <= progress * 4} />
        ))}
      </div>
      {modern
        ? tokens.flatMap((_, from) =>
            tokens.map((__, to) => {
              if (from === to) return null;
              const x1 = 88 + from * 178;
              const x2 = 88 + to * 178;
              const rotate = Math.atan2((to - from) * 12, x2 - x1) * (180 / Math.PI);
              return (
                <Line
                  key={`${from}-${to}`}
                  x={x1}
                  y={150 + from * 12}
                  width={Math.abs(x2 - x1)}
                  rotate={rotate}
                  color={from === 2 ? accent : colors.line}
                  progress={progress}
                />
              );
            }),
          )
        : [0, 1, 2].map((index) => (
            <Line
              key={index}
              x={146 + index * 178}
              y={206}
              width={32}
              color={accent}
              progress={Math.max(0, progress * 3 - index)}
            />
          ))}
    </div>
  );
};

const Tokens: React.FC<{accent: string; progress: number}> = ({accent, progress}) => (
  <div style={{width: 780, height: 430, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 56}}>
    <div style={{fontSize: 38, color: colors.muted}}>“模型正在理解语言。”</div>
    <div style={{display: 'flex', gap: 18}}>
      {['模型', '正在', '理解', '语言', '。'].map((token, index) => (
        <div key={token} style={{opacity: interpolate(progress, [index / 7, (index + 1) / 7], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})}}>
          <Token text={token} color={accent} active />
        </div>
      ))}
    </div>
    <div style={{display: 'flex', gap: 18, color: colors.muted, fontSize: 22}}>
      {[4812, 932, 7741, 328, 19].map((id) => (
        <div key={id} style={{width: 116, textAlign: 'center'}}>ID {id}</div>
      ))}
    </div>
  </div>
);

const Positions: React.FC<{accent: string; progress: number}> = ({accent, progress}) => (
  <div style={{position: 'relative', width: 820, height: 430}}>
    <svg width="820" height="260" viewBox="0 0 820 260" style={{position: 'absolute', top: 30}}>
      <polyline
        points={Array.from({length: 41}, (_, index) => {
          const x = index * 20;
          const y = 130 + Math.sin(index / 3) * 88;
          return `${x},${y}`;
        }).join(' ')}
        fill="none"
        stroke={accent}
        strokeWidth="5"
        strokeDasharray="1000"
        strokeDashoffset={1000 * (1 - progress)}
      />
    </svg>
    <div style={{position: 'absolute', bottom: 38, left: 0, right: 0, display: 'flex', justifyContent: 'space-between'}}>
      {['位置 0', '位置 1', '位置 2', '位置 3', '位置 4'].map((label, index) => (
        <div key={label} style={{width: 120, color: index / 5 < progress ? colors.text : colors.muted, fontSize: 24}}>{label}</div>
      ))}
    </div>
  </div>
);

const Qkv: React.FC<{accent: string; progress: number}> = ({accent, progress}) => (
  <div style={{width: 760, height: 430, display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
    <Token text="输入向量" color={accent} active />
    <div style={{fontSize: 46, color: colors.muted}}>×</div>
    {[
      ['Q', '我在找什么'],
      ['K', '我有什么线索'],
      ['V', '我传递什么'],
    ].map(([letter, label], index) => (
      <div key={letter} style={{opacity: interpolate(progress, [index * 0.16, 0.4 + index * 0.16], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})}}>
        <div style={{width: 154, height: 190, border: `2px solid ${index === 0 ? accent : colors.line}`, borderRadius: 6, background: colors.surface, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 24}}>
          <strong style={{fontSize: 64, color: index === 0 ? accent : colors.text}}>{letter}</strong>
          <span style={{fontSize: 20, color: colors.muted, textAlign: 'center'}}>{label}</span>
        </div>
      </div>
    ))}
  </div>
);

const Matrix: React.FC<{accent: string; progress: number}> = ({accent, progress}) => {
  const values = [0.08, 0.12, 0.69, 0.11, 0.34, 0.21, 0.13, 0.32, 0.17, 0.62, 0.09, 0.12, 0.41, 0.18, 0.31, 0.1];
  return (
    <div style={{display: 'grid', gridTemplateColumns: 'repeat(4, 108px)', gap: 10}}>
      {values.map((value, index) => {
        const visible = progress > index / values.length;
        return (
          <div key={index} style={{width: 108, height: 92, borderRadius: 4, background: value > 0.5 ? accent : colors.surfaceRaised, color: value > 0.5 ? colors.background : colors.text, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 25, fontWeight: 700, opacity: visible ? 1 : 0.15}}>
            {value.toFixed(2)}
          </div>
        );
      })}
    </div>
  );
};

const Heads: React.FC<{accent: string; progress: number}> = ({accent, progress}) => (
  <div style={{display: 'grid', gridTemplateColumns: 'repeat(2, 300px)', gap: 22}}>
    {['语法关系', '指代关系', '主题关系', '位置关系'].map((label, index) => (
      <div key={label} style={{height: 144, border: `2px solid ${index === Math.floor(progress * 4) % 4 ? accent : colors.line}`, borderRadius: 6, background: colors.surface, padding: 28, display: 'flex', alignItems: 'center', gap: 20}}>
        <Network size={42} color={index === Math.floor(progress * 4) % 4 ? accent : colors.muted} />
        <div><div style={{fontSize: 20, color: colors.muted}}>HEAD {index + 1}</div><div style={{fontSize: 28, marginTop: 8}}>{label}</div></div>
      </div>
    ))}
  </div>
);

const Block: React.FC<{accent: string; progress: number}> = ({accent, progress}) => (
  <div style={{position: 'relative', width: 720, height: 430}}>
    {[
      ['Multi-Head Attention', 40],
      ['Add & LayerNorm', 145],
      ['Feed Forward', 250],
      ['Add & LayerNorm', 355],
    ].map(([label, top], index) => (
      <div key={String(label)} style={{position: 'absolute', top: Number(top), left: 160, width: 410, height: 74, border: `2px solid ${index === 0 || index === 2 ? accent : colors.line}`, borderRadius: 5, background: colors.surface, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 25, opacity: interpolate(progress, [index * 0.18, index * 0.18 + 0.3], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})}}>{label}</div>
    ))}
    <div style={{position: 'absolute', left: 90, top: 76, width: 50, height: 310, borderLeft: `4px solid ${colors.yellow}`, borderTop: `4px solid ${colors.yellow}`, borderBottom: `4px solid ${colors.yellow}`, opacity: progress}} />
    <span style={{position: 'absolute', left: 4, top: 213, color: colors.yellow, fontSize: 22}}>Residual</span>
  </div>
);

const Training: React.FC<{accent: string; progress: number}> = ({accent, progress}) => (
  <div style={{width: 760, height: 430, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 38}}>
    <div style={{display: 'flex', gap: 18}}>
      {['Transformer', '预测', '下一个', 'Token'].map((token, index) => (
        <Token key={token} text={token} color={accent} active={index <= progress * 4} />
      ))}
    </div>
    <div style={{fontSize: 30, color: colors.muted}}>目标：P(tokenₜ | token₁ ... tokenₜ₋₁)</div>
    <div style={{height: 8, background: colors.line}}><div style={{width: `${progress * 100}%`, height: '100%', background: accent}} /></div>
  </div>
);

const Mask: React.FC<{accent: string; progress: number}> = ({accent, progress}) => (
  <div style={{display: 'grid', gridTemplateColumns: 'repeat(6, 70px)', gap: 8}}>
    {Array.from({length: 36}, (_, index) => {
      const row = Math.floor(index / 6);
      const column = index % 6;
      const allowed = column <= row;
      return <div key={index} style={{width: 70, height: 70, background: allowed ? accent : colors.surfaceRaised, opacity: allowed ? interpolate(progress, [index / 45, index / 45 + 0.3], [0.2, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}) : 0.25, borderRadius: 3}} />;
    })}
  </div>
);

const Cache: React.FC<{accent: string; progress: number}> = ({accent, progress}) => (
  <div style={{width: 760, height: 430, display: 'flex', alignItems: 'center', gap: 44}}>
    <div style={{display: 'grid', gridTemplateColumns: 'repeat(3, 118px)', gap: 12}}>
      {Array.from({length: 9}, (_, index) => <div key={index} style={{height: 82, borderRadius: 4, background: index / 9 < progress ? accent : colors.surfaceRaised, opacity: 0.35 + (index / 9 < progress ? 0.65 : 0)}} />)}
    </div>
    <div style={{fontSize: 42, color: colors.muted}}>→</div>
    <div style={{width: 220, height: 250, border: `3px solid ${accent}`, borderRadius: 6, background: colors.surface, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 28}}>
      <Database size={64} color={accent} />
      <strong style={{fontSize: 35}}>KV Cache</strong>
      <span style={{fontSize: 21, color: colors.muted}}>复用历史计算</span>
    </div>
  </div>
);

const iconForScene = (kind: EpisodeScene['kind']) => {
  if (kind === 'tokens') return Braces;
  if (kind === 'positions') return Binary;
  if (kind === 'qkv' || kind === 'matrix') return Sigma;
  if (kind === 'heads') return Network;
  if (kind === 'block') return Layers3;
  if (kind === 'training' || kind === 'mask') return BrainCircuit;
  if (kind === 'cache') return Database;
  if (kind === 'parallel') return Route;
  return Boxes;
};

export const SceneVisual: React.FC<{
  episode: Episode;
  scene: EpisodeScene;
  sceneIndex: number;
  sceneCount: number;
}> = ({episode, scene, sceneIndex, sceneCount}) => {
  const frame = useCurrentFrame();
  const {durationInFrames, fps} = useVideoConfig();
  const accent = accentColor(episode.accent);
  const enter = spring({frame, fps, config: {damping: 16, stiffness: 95, mass: 0.8}});
  const progress = interpolate(frame, [8, Math.max(20, durationInFrames - 18)], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const opacity = fade(frame, durationInFrames);
  const Icon = iconForScene(scene.kind);
  const titleWidth = [...scene.title].reduce(
    (width, character) => width + (/^[\x00-\x7F]$/.test(character) ? 0.56 : 1),
    0,
  );
  const titleFontSize = titleWidth > 19 ? 52 : titleWidth > 14 ? 58 : 64;

  let visual: React.ReactNode;
  switch (scene.kind) {
    case 'parallel':
      visual = <Parallel accent={accent} progress={progress} modern={scene.eyebrow === '新方法'} />;
      break;
    case 'tokens':
      visual = <Tokens accent={accent} progress={progress} />;
      break;
    case 'positions':
      visual = <Positions accent={accent} progress={progress} />;
      break;
    case 'qkv':
      visual = <Qkv accent={accent} progress={progress} />;
      break;
    case 'matrix':
      visual = <Matrix accent={accent} progress={progress} />;
      break;
    case 'heads':
      visual = <Heads accent={accent} progress={progress} />;
      break;
    case 'block':
      visual = <Block accent={accent} progress={progress} />;
      break;
    case 'training':
      visual = <Training accent={accent} progress={progress} />;
      break;
    case 'mask':
      visual = <Mask accent={accent} progress={progress} />;
      break;
    case 'cache':
      visual = <Cache accent={accent} progress={progress} />;
      break;
    default:
      visual = <Overview accent={accent} progress={progress} />;
  }

  return (
    <div style={{position: 'absolute', inset: 0, padding: '132px 88px 176px', opacity}}>
      <div style={{height: '100%', display: 'grid', gridTemplateColumns: '700px 1fr', gap: 48, alignItems: 'center'}}>
        <div style={{transform: `translateY(${(1 - enter) * 38}px)`, opacity: enter}}>
          <div style={{display: 'flex', alignItems: 'center', gap: 18, color: accent, fontSize: 22, fontWeight: 800}}>
            <Icon size={28} strokeWidth={2.4} />
            <span>{scene.eyebrow}</span>
          </div>
          <h1
            style={{
              fontFamily,
              fontSize: scene.kind === 'outro' ? Math.min(70, titleFontSize + 6) : titleFontSize,
              lineHeight: 1.14,
              margin: '28px 0 30px',
              fontWeight: 800,
              letterSpacing: 0,
              textWrap: 'balance',
            }}
          >
            {scene.title}
          </h1>
          <div style={{width: 88, height: 6, background: accent, marginBottom: 32}} />
          <p style={{fontSize: 30, lineHeight: 1.6, color: colors.muted, margin: 0, maxWidth: 600}}>{scene.caption}</p>
          <div style={{display: 'flex', alignItems: 'center', gap: 12, marginTop: 48, color: colors.muted, fontSize: 19}}>
            {Array.from({length: sceneCount}, (_, index) => <span key={index} style={{width: index === sceneIndex ? 32 : 9, height: 9, background: index === sceneIndex ? accent : colors.line, borderRadius: 4}} />)}
          </div>
        </div>
        <div style={{display: 'flex', alignItems: 'center', justifyContent: 'center', transform: `scale(${0.94 + enter * 0.06})`, opacity: enter}}>{visual}</div>
      </div>
    </div>
  );
};
