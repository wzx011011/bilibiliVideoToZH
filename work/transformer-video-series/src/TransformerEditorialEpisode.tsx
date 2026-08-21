import React from 'react';
import {
  AbsoluteFill,
  Audio,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {
  ArrowRight,
  Braces,
  BrainCircuit,
  Layers3,
  Network,
  ScanLine,
  Waypoints,
} from 'lucide-react';
import type {Episode} from './types';
import {fontFamily} from './theme';

export type TransformerEditorialEpisodeProps = {
  episode: Episode;
};

const editorial = {
  paper: '#f1f4f1',
  paperRaised: '#ffffff',
  ink: '#102a3a',
  muted: '#55707d',
  line: '#cad5d5',
  red: '#e4484b',
  teal: '#00a38c',
  yellow: '#f4c84c',
  dark: '#12242e',
};

type StoryCard = {
  section: string;
  kicker: string;
  title: string;
  supporting: string;
  weight: number;
  sentenceIndexes: number[];
  kind: 'hook' | 'shift' | 'contrast' | 'architecture' | 'block' | 'payoff';
};

const storyCards: StoryCard[] = [
  {
    section: '01 / BEFORE',
    kicker: '语言曾被迫排队处理',
    title: '先读完这个词，才能读下一个。',
    supporting: '循环神经网络按顺序传递状态。距离越远，信息要走的路越长。',
    weight: 1.08,
    sentenceIndexes: [0, 1],
    kind: 'hook',
  },
  {
    section: '02 / 2017',
    kicker: 'Attention Is All You Need',
    title: '让每个位置，直接看见全句。',
    supporting: 'Transformer 不再沿着一条链搬运上下文，而是先建立全局连接。',
    weight: 1.08,
    sentenceIndexes: [2],
    kind: 'shift',
  },
  {
    section: '03 / WHY IT WON',
    kicker: '两项工程优势',
    title: '并行训练。远距关系，一跳可达。',
    supporting: '这两个变化让语言建模可以随着数据和计算资源一起放大。',
    weight: 1.18,
    sentenceIndexes: [3],
    kind: 'contrast',
  },
  {
    section: '04 / ARCHITECTURE',
    kicker: '经典 Transformer',
    title: '编码器理解，解码器生成。',
    supporting: '今天的大语言模型通常保留解码器，但核心的信息交换机制没有变。',
    weight: 1.18,
    sentenceIndexes: [4],
    kind: 'architecture',
  },
  {
    section: '05 / THE BLOCK',
    kicker: '每一层都做三件事',
    title: '交换信息。独立处理。稳定堆叠。',
    supporting: '注意力层、前馈网络、残差连接和归一化，共同组成可扩展的积木。',
    weight: 1.25,
    sentenceIndexes: [5],
    kind: 'block',
  },
  {
    section: '06 / THE IDEA',
    kicker: '真正的变化',
    title: '把语言，变成可规模化的通用计算。',
    supporting: '重要的不是某一个公式，而是一个能持续扩展的系统结构。',
    weight: 0.93,
    sentenceIndexes: [6],
    kind: 'payoff',
  },
];

const splitNarration = (narration: string) =>
  narration
    .match(/[^。！？]+[。！？]?/g)
    ?.map((sentence) => sentence.trim())
    .filter(Boolean) ?? [narration];

const entry = (frame: number, fps: number, delay = 0) =>
  spring({
    frame: Math.max(0, frame - delay),
    fps,
    config: {damping: 18, stiffness: 120, mass: 0.75},
  });

const exit = (frame: number, duration: number) =>
  interpolate(frame, [duration - 11, duration], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

type SentenceTiming = {
  sentence: string;
  from: number;
  duration: number;
};

const getSentenceTimings = (episode: Episode, durationInFrames: number): SentenceTiming[] => {
  const sentences = splitNarration(episode.narration);
  const fallbackDurations = sentences.map((sentence) => Math.max(10, [...sentence].length));
  const sourceDurations =
    episode.narrationTimings?.length === sentences.length
      ? episode.narrationTimings
      : fallbackDurations;
  const totalDuration = sourceDurations.reduce((sum, duration) => sum + duration, 0);
  let cursor = 0;

  return sentences.map((sentence, index) => {
    const isLast = index === sentences.length - 1;
    const duration = isLast
      ? durationInFrames - cursor
      : Math.round((sourceDurations[index] / totalDuration) * durationInFrames);
    const timing = {sentence, from: cursor, duration};
    cursor += duration;
    return timing;
  });
};

const getCardTimings = (episode: Episode, durationInFrames: number) => {
  const sentenceTimings = getSentenceTimings(episode, durationInFrames);

  return storyCards.map((card) => {
    const firstSentence = sentenceTimings[card.sentenceIndexes[0]];
    const lastSentence = sentenceTimings[card.sentenceIndexes.at(-1) ?? 0];
    const from = firstSentence?.from ?? 0;
    const end = lastSentence ? lastSentence.from + lastSentence.duration : durationInFrames;
    return {card, from, duration: Math.max(1, end - from)};
  });
};

const SceneWipe: React.FC<{index: number}> = ({index}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const travel = interpolate(frame, [0, 7, 15, 24], [-125, 0, 0, 130], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const colors = [editorial.red, editorial.dark, editorial.teal, editorial.yellow];

  return (
    <AbsoluteFill style={{overflow: 'hidden', pointerEvents: 'none'}}>
      {colors.map((color, panelIndex) => (
        <div
          key={color}
          style={{
            position: 'absolute',
            top: 0,
            bottom: 0,
            left: `${panelIndex * 25 - 26}%`,
            width: '31%',
            background: color,
            transform: `translateX(${travel + panelIndex * 7}px) skewX(-12deg)`,
          }}
        />
      ))}
      <div
        style={{
          position: 'absolute',
          left: 86,
          bottom: 110,
          color: editorial.paperRaised,
          fontFamily,
          fontSize: 26,
          fontWeight: 850,
          letterSpacing: 0,
          opacity: interpolate(frame, [7, 12, 18, 24], [0, 1, 1, 0], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          }),
          transform: `translateY(${(1 - entry(frame, fps, 7)) * 20}px)`,
        }}
      >
        CHAPTER {String(index + 1).padStart(2, '0')}
      </div>
    </AbsoluteFill>
  );
};

const CardFrame: React.FC<{
  card: StoryCard;
  children: React.ReactNode;
}> = ({card, children}) => {
  const frame = useCurrentFrame();
  const {durationInFrames, fps} = useVideoConfig();
  const reveal = entry(frame, fps);
  const opacity = exit(frame, durationInFrames);
  const cameraScale = interpolate(frame, [0, durationInFrames], [1, 1.018], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const cameraShift = interpolate(frame, [0, durationInFrames], [0, -10], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill
      style={{
        background: editorial.paper,
        color: editorial.ink,
        fontFamily,
        opacity,
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          position: 'absolute',
          inset: 0,
          opacity: 0.5,
          backgroundImage:
            'linear-gradient(to right, transparent 0, transparent 239px, rgba(16,42,58,0.05) 240px, transparent 241px), linear-gradient(to bottom, transparent 0, transparent 179px, rgba(16,42,58,0.05) 180px, transparent 181px)',
          backgroundSize: '240px 180px',
        }}
      />
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          bottom: 0,
          width: 30,
          background: editorial.red,
          transform: `scaleY(${reveal})`,
          transformOrigin: 'top center',
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: 76,
          right: 76,
          top: 46,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          fontSize: 22,
          fontWeight: 800,
          letterSpacing: 0,
        }}
      >
        <div style={{display: 'flex', alignItems: 'center', gap: 16}}>
          <span style={{color: editorial.red}}>TRANSFORMER / VISUAL NOTES</span>
          <span style={{width: 54, height: 3, background: editorial.ink}} />
          <span style={{color: editorial.muted}}>TECH EXPLAINED</span>
        </div>
        <span style={{color: editorial.muted}}>{card.section}</span>
      </div>
      <div
        style={{
          position: 'absolute',
          left: 104,
          top: 150,
          width: 710,
          transform: `translateY(${(1 - reveal) * 36}px)`,
          opacity: reveal,
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            color: editorial.teal,
            fontSize: 26,
            fontWeight: 800,
          }}
        >
          <span style={{width: 12, height: 12, background: editorial.teal}} />
          {card.kicker}
        </div>
        <h1
          style={{
            margin: '26px 0 26px',
            fontSize: card.kind === 'payoff' ? 78 : 72,
            lineHeight: 1.12,
            letterSpacing: 0,
            fontWeight: 850,
          }}
        >
          {card.title}
        </h1>
        <p
          style={{
            margin: 0,
            color: editorial.muted,
            fontSize: 29,
            lineHeight: 1.55,
            maxWidth: 640,
          }}
        >
          {card.supporting}
        </p>
      </div>
      <div
        style={{
          position: 'absolute',
          left: 892,
          top: 156,
          right: 92,
          bottom: 190,
          transform: `translateX(${(1 - reveal) * 52 + cameraShift}px) scale(${cameraScale})`,
          transformOrigin: 'center center',
          opacity: reveal,
        }}
      >
        {children}
      </div>
      <div
        style={{
          position: 'absolute',
          left: 104,
          bottom: 178,
          display: 'flex',
          gap: 8,
          alignItems: 'center',
        }}
      >
        {storyCards.map((storyCard, index) => (
          <div
            key={storyCard.section}
            style={{
              height: 7,
              width: storyCard.section === card.section ? 42 : 14,
              background: storyCard.section === card.section ? editorial.red : editorial.line,
            }}
          />
        ))}
      </div>
      <div
        style={{
          position: 'absolute',
          left: 104,
          right: 104,
          bottom: 155,
          height: 1,
          background: editorial.line,
        }}
      />
    </AbsoluteFill>
  );
};

const Rail: React.FC<{label: string; index: number; active?: boolean}> = ({label, index, active}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const reveal = entry(frame, fps, 8 + index * 8);

  return (
    <div style={{display: 'flex', alignItems: 'center', gap: 14, opacity: reveal}}>
      <div
        style={{
          width: 98,
          height: 70,
          background: active ? editorial.red : editorial.paperRaised,
          border: `2px solid ${active ? editorial.red : editorial.ink}`,
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          fontSize: 24,
          fontWeight: 800,
          color: active ? editorial.paperRaised : editorial.ink,
          transform: `translateX(${(1 - reveal) * -18}px)`,
        }}
      >
        {label}
      </div>
      {index < 4 && <ArrowRight size={27} color={editorial.muted} strokeWidth={2.4} />}
    </div>
  );
};

const RnnVisual: React.FC = () => (
  <div
    style={{
      height: '100%',
      border: `2px solid ${editorial.ink}`,
      background: editorial.paperRaised,
      padding: '58px 50px',
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'space-between',
    }}
  >
    <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
      <span style={{fontSize: 26, fontWeight: 800}}>SEQUENTIAL PIPELINE</span>
      <BrainCircuit size={46} color={editorial.red} strokeWidth={2.2} />
    </div>
    <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
      {['我', '在', '学习', '注意力', '机制'].map((label, index) => (
        <Rail key={label} label={label} index={index} active={index === 3} />
      ))}
    </div>
    <div style={{display: 'flex', gap: 28, alignItems: 'center'}}>
      <div style={{width: 130, height: 12, background: editorial.red}} />
      <span style={{fontSize: 28, color: editorial.muted}}>信息只能沿序列前进</span>
    </div>
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(5, 1fr)',
        gap: 14,
        marginTop: 10,
      }}
    >
      {['t0', 't1', 't2', 't3', 't4'].map((tick, index) => (
        <div key={tick} style={{borderTop: `4px solid ${index === 4 ? editorial.red : editorial.line}`, paddingTop: 16, color: editorial.muted, fontSize: 22}}>
          {tick}
        </div>
      ))}
    </div>
  </div>
);

const ShiftVisual: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const reveal = entry(frame, fps, 5);
  const nodes = [
    {label: '我', x: 95, y: 330, color: editorial.red},
    {label: '在', x: 285, y: 150, color: editorial.yellow},
    {label: '学习', x: 495, y: 355, color: editorial.teal},
    {label: '注意力', x: 685, y: 120, color: editorial.red},
    {label: '机制', x: 845, y: 305, color: editorial.yellow},
  ];
  const pulseCycle = Math.max(1, Math.round(fps * 1.65));
  const pulseFrame = ((frame - 12) % pulseCycle + pulseCycle) % pulseCycle;
  const pulseProgress = interpolate(pulseFrame, [0, pulseCycle * 0.72, pulseCycle], [0, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const signalLinks = [
    [nodes[0], nodes[3]],
    [nodes[3], nodes[2]],
    [nodes[2], nodes[4]],
  ];

  return (
    <div style={{height: '100%', background: editorial.dark, position: 'relative', overflow: 'hidden', color: editorial.paperRaised}}>
      <div style={{position: 'absolute', top: 44, left: 48, right: 48, display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
        <div style={{fontSize: 24, fontWeight: 800, color: editorial.yellow}}>ATTENTION MAP</div>
        <Network size={42} color={editorial.teal} />
      </div>
      {nodes.flatMap((from, fromIndex) =>
        nodes.map((to, toIndex) => {
          if (toIndex <= fromIndex) return null;
          const dx = to.x - from.x;
          const dy = to.y - from.y;
          const length = Math.sqrt(dx * dx + dy * dy);
          const rotation = (Math.atan2(dy, dx) * 180) / Math.PI;
          return (
            <div
              key={`${from.label}-${to.label}`}
              style={{
                position: 'absolute',
                top: from.y + 30,
                left: from.x + 30,
                width: length * reveal,
                height: fromIndex === 0 || toIndex === 3 ? 4 : 2,
                background: fromIndex === 0 || toIndex === 3 ? editorial.teal : 'rgba(241,244,241,0.34)',
                transform: `rotate(${rotation}deg)`,
                transformOrigin: 'left center',
              }}
            />
          );
        }),
      )}
      {signalLinks.map(([from, to], index) => {
        const offset = (index / signalLinks.length + pulseProgress) % 1;
        const x = from.x + 60 + (to.x - from.x) * offset;
        const y = from.y + 36 + (to.y - from.y) * offset;
        return (
          <div
            key={`${from.label}-${to.label}-pulse`}
            style={{
              position: 'absolute',
              left: x - 10,
              top: y - 10,
              width: 20,
              height: 20,
              borderRadius: '50%',
              background: editorial.paperRaised,
              border: `4px solid ${editorial.teal}`,
              opacity: reveal,
              transform: `scale(${0.55 + pulseProgress * 0.45})`,
            }}
          />
        );
      })}
      {nodes.map((node, index) => {
        const nodeReveal = entry(frame, fps, 9 + index * 5);
        return (
          <div
            key={node.label}
            style={{
              position: 'absolute',
              left: node.x,
              top: node.y,
              width: 120,
              height: 72,
              background: node.color,
              color: editorial.ink,
              fontSize: 25,
              fontWeight: 850,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              opacity: nodeReveal,
              transform: `scale(${0.86 + nodeReveal * 0.14})`,
            }}
          >
            {node.label}
          </div>
        );
      })}
      <div style={{position: 'absolute', left: 48, bottom: 44, fontSize: 31, fontWeight: 700}}>
        任意位置 <span style={{color: editorial.yellow}}>直连</span> 其余位置
      </div>
    </div>
  );
};

const ContrastVisual: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const reveal = entry(frame, fps, 3);
  const stats = [
    ['01', 'Parallel', '所有位置同时计算', editorial.teal],
    ['02', 'One hop', '远距离关系直接连接', editorial.red],
  ] as const;

  return (
    <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, height: '100%'}}>
      {stats.map(([number, title, detail, color], index) => {
        const local = entry(frame, fps, 7 + index * 9);
        return (
          <div
            key={title}
            style={{
              background: index === 0 ? editorial.paperRaised : editorial.dark,
              color: index === 0 ? editorial.ink : editorial.paperRaised,
              border: `2px solid ${index === 0 ? editorial.ink : editorial.dark}`,
              padding: 42,
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
              opacity: local,
              transform: `translateY(${(1 - local) * 28}px)`,
            }}
          >
            <div style={{fontSize: 34, color, fontWeight: 850}}>{number}</div>
            <div>
              <div style={{fontSize: 57, lineHeight: 1, fontWeight: 850, marginBottom: 22}}>{title}</div>
              <div style={{fontSize: 27, lineHeight: 1.45, color: index === 0 ? editorial.muted : '#c7d4d3'}}>{detail}</div>
            </div>
            <div style={{height: 12, background: color, width: `${68 + index * 18}%`}} />
          </div>
        );
      })}
    </div>
  );
};

const ArchitectureVisual: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const blocks = [
    {label: 'INPUT', note: 'Tokens + Position', color: editorial.yellow},
    {label: 'ENCODER', note: '理解上下文', color: editorial.teal},
    {label: 'DECODER', note: '预测下一个 Token', color: editorial.red},
    {label: 'OUTPUT', note: '生成文本', color: editorial.ink},
  ];

  return (
    <div style={{height: '100%', background: editorial.paperRaised, border: `2px solid ${editorial.ink}`, padding: 48}}>
      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 46}}>
        <span style={{fontSize: 26, fontWeight: 850}}>CLASSIC TRANSFORMER</span>
        <Layers3 size={44} color={editorial.red} />
      </div>
      <div style={{display: 'flex', gap: 16, alignItems: 'center', height: 370}}>
        {blocks.map((block, index) => {
          const reveal = entry(frame, fps, index * 9);
          return (
            <React.Fragment key={block.label}>
              <div
                style={{
                  flex: 1,
                  height: index === 2 ? 268 : 212,
                  background: index === 2 ? editorial.dark : editorial.paper,
                  border: `3px solid ${block.color}`,
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'space-between',
                  padding: 22,
                  opacity: reveal,
                  transform: `translateY(${(1 - reveal) * 32}px)`,
                  color: index === 2 ? editorial.paperRaised : editorial.ink,
                }}
              >
                <div style={{fontSize: 22, color: block.color, fontWeight: 850}}>0{index + 1}</div>
                <div style={{fontSize: 34, fontWeight: 850, lineHeight: 1.05}}>{block.label}</div>
                <div style={{fontSize: 20, lineHeight: 1.35, color: index === 2 ? '#c9dad7' : editorial.muted}}>{block.note}</div>
              </div>
              {index < blocks.length - 1 && <ArrowRight size={32} color={editorial.muted} />}
            </React.Fragment>
          );
        })}
      </div>
      <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
        <div style={{fontSize: 28, color: editorial.muted}}>现代 LLM 通常采用 Decoder-only 结构</div>
        <div style={{display: 'flex', gap: 12}}>
          <div style={{padding: '8px 14px', background: editorial.teal, color: editorial.ink, fontSize: 20, fontWeight: 850}}>ENCODER x N</div>
          <div style={{padding: '8px 14px', background: editorial.red, color: editorial.paperRaised, fontSize: 20, fontWeight: 850}}>DECODER x N</div>
        </div>
      </div>
    </div>
  );
};

const BlockVisual: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const parts = [
    {label: 'ATTENTION', detail: '交换 Token 之间的信息', icon: Network, color: editorial.teal},
    {label: 'FEED FORWARD', detail: '每个位置独立处理', icon: Braces, color: editorial.red},
    {label: 'RESIDUAL + NORM', detail: '让深层网络稳定堆叠', icon: ScanLine, color: editorial.yellow},
  ];

  return (
    <div style={{height: '100%', display: 'flex', flexDirection: 'column', gap: 18}}>
      {parts.map((part, index) => {
        const reveal = entry(frame, fps, 5 + index * 9);
        const Icon = part.icon;
        return (
          <div
            key={part.label}
            style={{
              flex: 1,
              background: editorial.paperRaised,
              borderLeft: `18px solid ${part.color}`,
              borderTop: `2px solid ${editorial.ink}`,
              borderRight: `2px solid ${editorial.ink}`,
              borderBottom: `2px solid ${editorial.ink}`,
              padding: '28px 34px',
              display: 'flex',
              alignItems: 'center',
              gap: 30,
              opacity: reveal,
              transform: `translateX(${(1 - reveal) * 34}px)`,
            }}
          >
            <Icon size={46} color={part.color} strokeWidth={2.2} />
            <div>
              <div style={{fontSize: 33, fontWeight: 850, letterSpacing: 0}}>{part.label}</div>
              <div style={{fontSize: 24, color: editorial.muted, marginTop: 8}}>{part.detail}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
};

const PayoffVisual: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const pillars = [
    {label: 'STRUCTURE', value: '并行', color: editorial.red},
    {label: 'DATA', value: '扩展', color: editorial.teal},
    {label: 'COMPUTE', value: '增长', color: editorial.yellow},
  ];

  return (
    <div style={{height: '100%', background: editorial.dark, color: editorial.paperRaised, padding: 48, display: 'flex', flexDirection: 'column', justifyContent: 'space-between'}}>
      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
        <span style={{fontSize: 26, fontWeight: 850, color: editorial.yellow}}>SCALING SYSTEM</span>
        <Waypoints size={44} color={editorial.teal} />
      </div>
      <div style={{display: 'flex', alignItems: 'end', gap: 24, height: 350}}>
        {pillars.map((pillar, index) => {
          const reveal = entry(frame, fps, 8 + index * 10);
          const height = 164 + index * 70;
          return (
            <div key={pillar.label} style={{flex: 1, height, background: pillar.color, color: editorial.ink, padding: 22, display: 'flex', flexDirection: 'column', justifyContent: 'space-between', transform: `scaleY(${reveal})`, transformOrigin: 'bottom center'}}>
              <div style={{fontSize: 18, fontWeight: 850}}>{pillar.label}</div>
              <div style={{fontSize: 46, fontWeight: 850}}>{pillar.value}</div>
            </div>
          );
        })}
      </div>
      <div style={{fontSize: 32, lineHeight: 1.35}}>同一个架构，随着规模持续变强。</div>
    </div>
  );
};

const CardVisual: React.FC<{kind: StoryCard['kind']}> = ({kind}) => {
  switch (kind) {
    case 'hook':
      return <RnnVisual />;
    case 'shift':
      return <ShiftVisual />;
    case 'contrast':
      return <ContrastVisual />;
    case 'architecture':
      return <ArchitectureVisual />;
    case 'block':
      return <BlockVisual />;
    case 'payoff':
      return <PayoffVisual />;
  }
};

const Subtitles: React.FC<{episode: Episode}> = ({episode}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const sentenceTimings = getSentenceTimings(episode, durationInFrames);
  const activeIndex = sentenceTimings.findIndex(
    ({from, duration}) => frame >= from && frame < from + duration,
  );
  const activeSentence =
    sentenceTimings[activeIndex === -1 ? sentenceTimings.length - 1 : activeIndex]?.sentence ??
    episode.narration;

  return (
    <div
      style={{
        position: 'absolute',
        left: 104,
        right: 104,
        bottom: 38,
        minHeight: 78,
        background: editorial.paperRaised,
        borderTop: `4px solid ${editorial.ink}`,
        display: 'grid',
        gridTemplateColumns: '94px 1fr',
        alignItems: 'center',
        color: editorial.ink,
        fontFamily,
      }}
    >
      <div style={{height: '100%', background: editorial.red, display: 'flex', alignItems: 'center', justifyContent: 'center', color: editorial.paperRaised, fontSize: 21, fontWeight: 850}}>
        VOICE
      </div>
      <div style={{padding: '13px 32px', fontSize: 28, lineHeight: 1.4, fontWeight: 700, textAlign: 'center'}}>{activeSentence}</div>
    </div>
  );
};

const Progress: React.FC = () => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const progress = interpolate(frame, [0, durationInFrames - 1], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <div style={{position: 'absolute', top: 0, left: 0, right: 0, height: 8, background: editorial.line}}>
      <div style={{height: '100%', width: `${progress * 100}%`, background: editorial.teal}} />
    </div>
  );
};

export const TransformerEditorialEpisode: React.FC<TransformerEditorialEpisodeProps> = ({episode}) => {
  const {durationInFrames} = useVideoConfig();
  const timings = getCardTimings(episode, durationInFrames);

  return (
    <AbsoluteFill style={{background: editorial.paper, fontFamily}}>
      <Audio src={staticFile(episode.audio)} />
      {timings.map(({card, from, duration}) => {
        return (
          <Sequence key={card.section} from={from} durationInFrames={duration}>
            <CardFrame card={card}>
              <CardVisual kind={card.kind} />
            </CardFrame>
          </Sequence>
        );
      })}
      <Subtitles episode={episode} />
      <Progress />
      {timings.slice(1).map(({from}, index) => (
        <Sequence key={`wipe-${from}`} from={from} durationInFrames={26}>
          <SceneWipe index={index + 1} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
