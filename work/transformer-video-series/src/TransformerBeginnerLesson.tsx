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
  BrainCircuit,
  CircleHelp,
  Database,
  Eye,
  Layers3,
  Network,
  Repeat2,
  ScanLine,
  TriangleAlert,
} from 'lucide-react';
import lessonTiming from '../public/audio/transformer-beginner-10min.neural.timing.json';
import {fontFamily} from './theme';

export type TransformerBeginnerLessonProps = {audio: string};

const palette = {
  paper: '#f4f6f2', white: '#ffffff', ink: '#102a3a', muted: '#59737d', line: '#cbd7d6',
  red: '#e84b4f', teal: '#00a48e', yellow: '#f5c84c', navy: '#112832',
  paleRed: '#f8dfe0', paleTeal: '#d9f0ec', paleYellow: '#fff1bd',
};

const sections = [
  ['起点 / 一句话', '让每个词，都能参考全句。', 'Transformer 的核心不是背公式，而是让信息不再只沿一条链传递。', 'hook'],
  ['问题 / 语言', '计算机一开始，只看见符号。', '它不知道“它”指谁，也不知道词与词之间有什么关系。', 'ambiguity'],
  ['步骤 01 / TOKEN', '先把文字，切成编号的积木。', 'Token 可以是字、词片段或标点，是模型手里的输入编号。', 'tokens'],
  ['步骤 02 / VECTOR', '再把编号，变成可计算的坐标。', '向量是一串数字坐标，让神经网络能够比较和变换文字。', 'vectors'],
  ['旧方法 / RNN', '一个词接一个词，信息排队传。', '顺序自然存在，但长距离信息难保留，训练也难充分并行。', 'rnn'],
  ['突破 / ATTENTION', '处理一个词时，直接查看全句。', '“它”可以立刻参考“书”“桌子”和“很重”等位置。', 'attention'],
  ['直觉 / 权重', '注意力不是选择，而是调节音量。', '每个位置都有不同权重，重要线索会贡献更多信息。', 'weights'],
  ['机制 / QKV', 'Query 提问，Key 匹配，Value 传递内容。', '这三个角色把“我该参考谁”变成一套可学习的比较过程。', 'qkv'],
  ['计算 / SOFTMAX', '匹配分数，最后变成比例。', '分数变成总和为一的权重，再对信息加权汇总。', 'softmax'],
  ['扩展 / MULTI-HEAD', '同一句话，同时用多个角度读。', '不同头分别关注语法、指代、否定、时间或主题。', 'heads'],
  ['顺序 / POSITION', '词有含义，也要有座位号。', '位置编码让模型知道 Token 出现在哪里，不会丢掉词序。', 'positions'],
  ['积木 / BLOCK', '交换信息，再独立消化。', '注意力层负责沟通，前馈网络负责处理；残差和归一化保证稳定。', 'block'],
  ['结构 / ENCODER + DECODER', '先理解输入，再生成输出。', '经典 Transformer 有编码器和解码器，现代 GPT 常保留解码器。', 'architecture'],
  ['生成 / GPT', '每一步，只预测下一个 Token。', '训练可并行读完整句，生成却必须基于已写内容一步一步继续。', 'generation'],
  ['学习 / TRAINING', '猜错下一个词，再微调参数。', '海量文本上的重复预测，让模型逐渐学会哪些线索通常重要。', 'training'],
  ['工程 / KV CACHE', '算过的历史，不必重复再算。', '缓存 Key 和 Value 能加快生成，但长上下文也会占更多显存。', 'cache'],
  ['边界 / 保持清醒', '关联强，不等于真正理解。', '模型会犯错、会编造，也可能继承训练数据中的偏见。', 'limits'],
  ['总结 / RECAP', '从 Token 到下一个 Token。', '理解“谁看谁、看多少、怎样继续写”，就抓住了 Transformer 的骨架。', 'recap'],
] as const;

type VisualKind = (typeof sections)[number][3];
type SubtitleCue = {text: string; from: number; duration: number};
type Timing = {paragraphDurations: number[]; subtitleCues: SubtitleCue[]};
const timing = lessonTiming as Timing;

const show = (frame: number, fps: number, delay = 0) => spring({frame: Math.max(0, frame - delay), fps, config: {damping: 18, stiffness: 120, mass: 0.75}});

const getTimings = (durationInFrames: number) => {
  const total = timing.paragraphDurations.reduce((sum, value) => sum + value, 0);
  let cursor = 0;
  return sections.map((section, index) => {
    const duration = index === sections.length - 1 ? durationInFrames - cursor : Math.round((timing.paragraphDurations[index] / total) * durationInFrames);
    const value = {section, from: cursor, duration};
    cursor += duration;
    return value;
  });
};

const Arrow: React.FC<{color?: string}> = ({color = palette.muted}) => <ArrowRight size={31} color={color} strokeWidth={2.4} />;

const Box: React.FC<{label: string; note?: string; color?: string; dark?: boolean; index?: number}> = ({label, note, color = palette.teal, dark = false, index = 0}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const visible = show(frame, fps, index * 6 + 5);
  return <div style={{minWidth: 108, padding: '18px 16px', background: dark ? palette.navy : palette.white, border: `3px solid ${color}`, color: dark ? palette.white : palette.ink, opacity: visible, transform: `translateY(${(1 - visible) * 18}px)`}}><div style={{fontSize: 24, fontWeight: 850, lineHeight: 1.1}}>{label}</div>{note && <div style={{fontSize: 16, lineHeight: 1.35, marginTop: 8, color: dark ? '#d5e2df' : palette.muted}}>{note}</div>}</div>;
};

const Panel: React.FC<{label: string; children: React.ReactNode}> = ({label, children}) => <div style={{height: '100%', background: palette.white, border: `2px solid ${palette.ink}`, position: 'relative', overflow: 'hidden'}}><div style={{position: 'absolute', top: 26, left: 32, color: palette.muted, fontSize: 19, fontWeight: 850}}>{label}</div>{children}</div>;

const Node: React.FC<{label: string; x: number; y: number; color: string; index: number}> = ({label, x, y, color, index}) => <div style={{position: 'absolute', left: x, top: y, width: 102, height: 64, display: 'flex', alignItems: 'center', justifyContent: 'center', background: color, color: palette.ink, fontSize: 23, fontWeight: 850}}><Box label={label} color={color} index={index} /></div>;

const Link: React.FC<{from: [number, number]; to: [number, number]; color: string; width?: number}> = ({from, to, color, width = 3}) => {
  const dx = to[0] - from[0]; const dy = to[1] - from[1]; const length = Math.sqrt(dx * dx + dy * dy); const rotate = (Math.atan2(dy, dx) * 180) / Math.PI;
  return <div style={{position: 'absolute', left: from[0], top: from[1], width: length, height: width, background: color, transform: `rotate(${rotate}deg)`, transformOrigin: 'left center'}} />;
};

const Diagram: React.FC<{kind: VisualKind}> = ({kind}) => {
  const frame = useCurrentFrame();
  const pulse = interpolate(frame % 80, [0, 40, 80], [0.3, 1, 0.3]);
  const words = ['我', '把', '书', '放到', '桌子', '因为', '它', '很重'];
  const rows = (items: Array<[string, string, string]>) => <div style={{position: 'absolute', left: 46, right: 46, top: 120, display: 'grid', gap: 18}}>{items.map(([left, value, color]) => <div key={left} style={{display: 'grid', gridTemplateColumns: '100px 1fr 70px', gap: 15, alignItems: 'center'}}><span style={{fontSize: 24, fontWeight: 850}}>{left}</span><div style={{height: 30, background: palette.paper, border: `1px solid ${palette.line}`}}><div style={{width: value, height: '100%', background: color}} /></div><span style={{fontSize: 20, color, fontWeight: 850}}>{value}</span></div>)}</div>;
  switch (kind) {
    case 'hook': return <Panel label="ONE SENTENCE / ALL CONNECTED"><div style={{position: 'absolute', left: 32, right: 32, top: 175, display: 'flex', gap: 9, alignItems: 'center'}}>{words.map((word, index) => <Box key={word} label={word} color={index === 2 || index === 6 ? palette.red : palette.teal} index={index} />)}</div><Link from={[255, 300]} to={[700, 300]} color={palette.red} width={6} /><div style={{position: 'absolute', top: 375, left: 80, right: 80, textAlign: 'center', fontSize: 30, fontWeight: 800}}>“它”可以直接参考“书”，不用排队等消息。</div></Panel>;
    case 'ambiguity': return <Panel label="LANGUAGE NEEDS CONTEXT"><div style={{position: 'absolute', left: 38, right: 38, top: 128, display: 'grid', gap: 22}}>{[['我把书放到桌子上，因为它很重。', palette.paleRed], ['我把书放到桌子上，因为它很旧。', palette.paleTeal]].map(([text, background]) => <div key={text} style={{padding: 26, background, borderLeft: `14px solid ${background === palette.paleRed ? palette.red : palette.teal}`, fontSize: 27, fontWeight: 800}}>{text}</div>)}</div><BrainCircuit size={82} color={palette.yellow} style={{position: 'absolute', right: 52, bottom: 48}} /></Panel>;
    case 'tokens': return <Panel label="TEXT BECOMES TOKENS"><div style={{position: 'absolute', top: 132, left: 44, fontSize: 27, color: palette.muted}}>Transformer 很有用</div><div style={{position: 'absolute', left: 42, right: 42, top: 205, display: 'flex', gap: 16}}>{['Transform', 'er', '很', '有', '用'].map((word, index) => <Box key={word} label={word} note={`#${index + 104}`} color={[palette.red, palette.yellow, palette.teal][index % 3]} index={index} />)}</div><div style={{position: 'absolute', left: 44, bottom: 64, fontSize: 25, color: palette.muted}}>先编号，再在后续网络里逐步形成语义。</div></Panel>;
    case 'vectors': return <Panel label="EMBEDDING SPACE"><div style={{position: 'absolute', left: 90, right: 70, top: 105, bottom: 70, borderLeft: `2px solid ${palette.line}`, borderBottom: `2px solid ${palette.line}`}} />{[['猫', 190, 260, palette.red], ['狗', 310, 210, palette.teal], ['书', 500, 160, palette.red], ['桌子', 590, 290, palette.teal], ['发动机', 700, 410, palette.yellow]].map(([label, x, y, color], index) => <Node key={String(label)} label={String(label)} x={Number(x)} y={Number(y)} color={String(color)} index={index} />)}</Panel>;
    case 'rnn': return <Panel label="RNN / SEQUENTIAL PATH"><div style={{position: 'absolute', left: 38, right: 38, top: 220, display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>{['词 1', '词 2', '词 3', '词 4', '词 5'].map((label, index) => <React.Fragment key={label}><Box label={label} color={palette.red} index={index} />{index < 4 && <Arrow color={palette.red} />}</React.Fragment>)}</div><div style={{position: 'absolute', left: 44, bottom: 70, color: palette.red, fontSize: 27, fontWeight: 850}}>路径越长，越难保存早期信息，也越难并行。</div></Panel>;
    case 'attention': { const nodes = [['我', 80, 300, palette.red], ['书', 250, 140, palette.yellow], ['桌子', 450, 340, palette.teal], ['它', 650, 150, palette.red], ['很重', 790, 300, palette.yellow]] as const; return <Panel label="ATTENTION MAP">{nodes.flatMap((from, a) => nodes.map((to, b) => b > a ? <Link key={`${from[0]}-${to[0]}`} from={[from[1] + 50, from[2] + 32]} to={[to[1] + 50, to[2] + 32]} color={from[0] === '它' || to[0] === '它' ? palette.teal : palette.line} width={from[0] === '它' || to[0] === '它' ? 4 : 2} /> : null))}{nodes.map(([label, x, y, color], index) => <Node key={label} label={label} x={x} y={y} color={color} index={index} />)}<Eye size={40} color={palette.yellow} style={{position: 'absolute', right: 42, top: 26}} /></Panel>; }
    case 'weights': return <Panel label="ATTENTION = VOLUME CONTROL">{rows([['书', '82%', palette.red], ['桌子', '42%', palette.teal], ['因为', '20%', palette.yellow], ['上', '9%', palette.muted]])}<div style={{position: 'absolute', right: 50, bottom: 45, fontSize: 28, fontWeight: 850, color: palette.teal}}>看多少，不是二选一。</div></Panel>;
    case 'qkv': return <Panel label="QUERY / KEY / VALUE"><div style={{position: 'absolute', top: 160, left: 40, right: 40, display: 'flex', alignItems: 'center', gap: 14}}><Box label="QUERY" note="我想找什么？" color={palette.red} /><Arrow color={palette.red} /><Box label="KEY" note="我有什么线索？" color={palette.yellow} index={1} /><Arrow color={palette.teal} /><Box label="VALUE" note="我能提供什么？" color={palette.teal} index={2} /></div><div style={{position: 'absolute', left: 78, right: 78, bottom: 82, display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 28, fontWeight: 850}}><CircleHelp color={palette.red} size={48} />提问 - 匹配 - 取回信息<Network color={palette.teal} size={48} /></div></Panel>;
    case 'softmax': return <Panel label="SCORE -> SOFTMAX -> WEIGHTED SUM"><div style={{position: 'absolute', left: 38, right: 38, top: 130, display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}><Box label="匹配分数" note="8.2 / 3.1 / 1.0" color={palette.red} /><Arrow /><Box label="SOFTMAX" note="总和变成 1" color={palette.yellow} index={1} /><Arrow /><Box label="加权汇总" note="新的 Token 表示" color={palette.teal} index={2} /></div><div style={{position: 'absolute', left: 75, right: 75, bottom: 72, display: 'flex', gap: 12, alignItems: 'end', height: 105}}>{[[60, palette.red], [25, palette.teal], [10, palette.yellow], [5, palette.line]].map(([percent, color]) => <div key={percent} style={{flex: 1, height: `${Number(percent) + 18}%`, background: color, display: 'flex', alignItems: 'end', justifyContent: 'center', paddingBottom: 7, fontWeight: 850}}>{percent}%</div>)}</div></Panel>;
    case 'heads': return <Panel label="MULTI-HEAD ATTENTION"><div style={{position: 'absolute', top: 112, left: 38, right: 38, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18}}>{[['HEAD 01', '主谓关系', palette.red], ['HEAD 02', '代词指代', palette.teal], ['HEAD 03', '否定与转折', palette.yellow], ['HEAD 04', '时间与地点', palette.navy]].map(([head, note, color]) => <div key={head} style={{height: 142, padding: 22, borderTop: `10px solid ${color}`, background: color === palette.navy ? palette.navy : palette.white, color: color === palette.navy ? palette.white : palette.ink}}><div style={{fontWeight: 850, color}}>{head}</div><div style={{fontSize: 26, fontWeight: 850, marginTop: 22}}>{note}</div></div>)}</div><Layers3 size={54} color={palette.teal} style={{position: 'absolute', right: 44, bottom: 42}} /></Panel>;
    case 'positions': return <Panel label="TOKEN + POSITION"><div style={{position: 'absolute', top: 145, left: 48, right: 48, display: 'flex', gap: 16}}>{['我', '喜欢', '你'].map((word, index) => <div key={word} style={{flex: 1, textAlign: 'center'}}><div style={{padding: 18, background: [palette.red, palette.teal, palette.yellow][index], fontSize: 29, fontWeight: 850}}>{word}</div><div style={{marginTop: 14, border: `2px solid ${palette.ink}`, padding: 12, fontSize: 22, fontWeight: 850}}>位置 {index + 1}</div></div>)}</div><div style={{position: 'absolute', left: 48, right: 48, bottom: 96, textAlign: 'center', fontSize: 29, fontWeight: 850}}>词的含义 <span style={{color: palette.red}}>+</span> 座位号 <Arrow color={palette.teal} /> 带顺序的输入</div></Panel>;
    case 'block': return <Panel label="ONE TRANSFORMER BLOCK"><div style={{position: 'absolute', top: 105, left: 100, right: 100, display: 'grid', gap: 10}}>{[['输入 Token', palette.paleYellow], ['多头注意力：交换信息', palette.paleTeal], ['残差 + 归一化：稳定', palette.paleRed], ['前馈网络：独立消化', palette.paleTeal], ['残差 + 归一化：稳定', palette.paleRed]].map(([label, background], index) => <div key={`${label}-${index}`} style={{height: 66, background, borderLeft: `12px solid ${[palette.yellow, palette.teal, palette.red][index % 3]}`, display: 'flex', alignItems: 'center', paddingLeft: 20, fontSize: 23, fontWeight: 850}}>{label}</div>)}</div></Panel>;
    case 'architecture': return <Panel label="CLASSIC TRANSFORMER"><div style={{position: 'absolute', left: 34, right: 34, top: 185, display: 'flex', alignItems: 'center', gap: 12}}>{[['输入', 'Token + 位置', palette.yellow], ['编码器', '理解整句', palette.teal], ['解码器', '预测下一个', palette.red], ['输出', '生成文本', palette.navy]].map(([label, note, color], index) => <React.Fragment key={label}><Box label={label} note={note} color={color} dark={color === palette.navy} index={index} />{index < 3 && <Arrow />}</React.Fragment>)}</div><div style={{position: 'absolute', left: 42, right: 42, bottom: 65, padding: 16, background: palette.paleYellow, fontSize: 24, fontWeight: 850}}>GPT 常用 Decoder-only：核心积木没有变。</div></Panel>;
    case 'generation': return <Panel label="NEXT TOKEN PREDICTION"><div style={{position: 'absolute', left: 46, right: 46, top: 135, fontSize: 30, fontWeight: 850}}>Transformer 的核心是 <span style={{color: palette.red}}>注意力</span></div>{rows([['注意力', '72%', palette.red], ['向量', '16%', palette.teal], ['缓存', '8%', palette.yellow], ['卷积', '4%', palette.line]])}<Repeat2 size={46} color={palette.teal} style={{position: 'absolute', right: 46, bottom: 45}} /></Panel>;
    case 'training': return <Panel label="TRAIN BY PREDICTING"><div style={{position: 'absolute', left: 54, right: 54, top: 130, display: 'grid', gap: 22}}><div style={{padding: 25, background: palette.paleYellow, fontSize: 30, fontWeight: 850}}>今天天气很 <span style={{color: palette.red}}>?</span></div><div style={{display: 'flex', gap: 18, alignItems: 'center'}}><Box label="模型猜：热" color={palette.red} /><Arrow /><Box label="答案：好" color={palette.teal} index={1} /></div><div style={{fontSize: 26, color: palette.muted}}>计算误差，微调参数，再看下一个例子。</div></div></Panel>;
    case 'cache': return <Panel label="KV CACHE / REUSE HISTORY"><div style={{position: 'absolute', top: 145, left: 35, right: 35, display: 'flex', alignItems: 'center', gap: 12}}>{['T1', 'T2', 'T3', 'T4', '新 Token'].map((token, index) => <React.Fragment key={token}><Box label={token} note={index < 4 ? 'K + V 缓存' : '只算新增'} color={index < 4 ? palette.teal : palette.red} index={index} />{index < 4 && <Arrow />}</React.Fragment>)}</div><Database size={58} color={palette.yellow} style={{position: 'absolute', left: 44, bottom: 45}} /><div style={{position: 'absolute', left: 120, bottom: 60, fontSize: 26, fontWeight: 850}}>更快生成 <span style={{color: palette.red}}>但</span> 更长上下文占更多显存。</div></Panel>;
    case 'limits': return <Panel label="USEFUL, NOT MAGIC"><div style={{position: 'absolute', left: 42, right: 42, top: 120, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18}}><div style={{height: 140, padding: 22, borderTop: `10px solid ${palette.red}`}}><TriangleAlert size={34} color={palette.red} /><div style={{fontSize: 24, fontWeight: 850, marginTop: 16}}>可能编造内容</div></div><div style={{height: 140, padding: 22, borderTop: `10px solid ${palette.yellow}`}}><ScanLine size={34} color={palette.yellow} /><div style={{fontSize: 24, fontWeight: 850, marginTop: 16}}>可能继承偏见</div></div><div style={{height: 140, padding: 22, borderTop: `10px solid ${palette.teal}`}}><CircleHelp size={34} color={palette.teal} /><div style={{fontSize: 24, fontWeight: 850, marginTop: 16}}>权重不等于理解</div></div><div style={{height: 140, padding: 22, borderTop: `10px solid ${palette.navy}`, background: palette.navy, color: palette.white}}><Eye size={34} color={palette.yellow} /><div style={{fontSize: 24, fontWeight: 850, marginTop: 16}}>重要信息要核验</div></div></div></Panel>;
    case 'recap': return <Panel label="THE TRANSFORMER LOOP"><div style={{position: 'absolute', left: 30, right: 30, top: 185, display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>{[['文字', palette.red], ['Token', palette.yellow], ['向量 + 位置', palette.teal], ['注意力 + FFN', palette.navy], ['下一个 Token', palette.red]].map(([label, color], index) => <React.Fragment key={label}><Box label={label} color={color} dark={color === palette.navy} index={index} />{index < 4 && <Arrow color={palette.teal} />}</React.Fragment>)}</div><div style={{position: 'absolute', left: 42, right: 42, bottom: 80, textAlign: 'center', fontSize: 27, fontWeight: 850, color: palette.teal}}>谁看谁，看的多少，怎样更快继续写。</div></Panel>;
  }
};

const LessonCard: React.FC<{index: number; section: (typeof sections)[number]}> = ({index, section}) => {
  const frame = useCurrentFrame(); const {fps, durationInFrames} = useVideoConfig(); const visible = show(frame, fps); const opacity = interpolate(frame, [durationInFrames - 16, durationInFrames], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return <AbsoluteFill style={{background: palette.paper, color: palette.ink, fontFamily, opacity, overflow: 'hidden'}}><div style={{position: 'absolute', inset: 0, opacity: 0.5, backgroundImage: `linear-gradient(to right, transparent 0, transparent 239px, rgba(16,42,58,0.05) 240px, transparent 241px), linear-gradient(to bottom, transparent 0, transparent 179px, rgba(16,42,58,0.05) 180px, transparent 181px)`, backgroundSize: '240px 180px'}} /><div style={{position: 'absolute', left: 0, top: 0, bottom: 0, width: 28, background: palette.red}} /><div style={{position: 'absolute', top: 42, left: 74, right: 74, display: 'flex', justifyContent: 'space-between', fontSize: 20, fontWeight: 850}}><div><span style={{color: palette.red}}>TRANSFORMER / FROM ZERO</span><span style={{margin: '0 16px', color: palette.ink}}>---</span><span style={{color: palette.muted}}>10 MINUTE LESSON</span></div><span style={{color: palette.muted}}>第 {String(index + 1).padStart(2, '0')} / {String(sections.length).padStart(2, '0')} 章</span></div><div style={{position: 'absolute', left: 94, top: 138, width: 700, opacity: visible, transform: `translateY(${(1 - visible) * 30}px)`}}><div style={{fontSize: 24, color: palette.teal, fontWeight: 850}}><span style={{display: 'inline-block', width: 12, height: 12, background: palette.teal, marginRight: 12}} />{section[0]}</div><h1 style={{fontSize: section[1].length > 18 ? 60 : 70, lineHeight: 1.14, margin: '26px 0'}}>{section[1]}</h1><p style={{fontSize: 28, lineHeight: 1.55, color: palette.muted, margin: 0, maxWidth: 620}}>{section[2]}</p></div><div style={{position: 'absolute', left: 850, right: 78, top: 142, bottom: 180, opacity: visible, transform: `translateX(${(1 - visible) * 42}px)`}}><Diagram kind={section[3]} /></div><div style={{position: 'absolute', left: 94, bottom: 154, display: 'flex', gap: 7}}>{sections.map((_, dot) => <div key={dot} style={{width: dot === index ? 28 : 8, height: 6, background: dot === index ? palette.red : palette.line}} />)}</div><div style={{position: 'absolute', left: 94, right: 94, bottom: 132, height: 1, background: palette.line}} /></AbsoluteFill>;
};

const Wipe: React.FC<{chapter: number}> = ({chapter}) => { const frame = useCurrentFrame(); const travel = interpolate(frame, [0, 8, 18, 27], [-115, 0, 0, 125], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}); return <AbsoluteFill style={{overflow: 'hidden'}}>{[palette.red, palette.navy, palette.teal, palette.yellow].map((color, index) => <div key={color} style={{position: 'absolute', top: 0, bottom: 0, left: `${index * 25 - 26}%`, width: '31%', background: color, transform: `translateX(${travel + index * 7}px) skewX(-12deg)`}} />)}<div style={{position: 'absolute', left: 78, bottom: 84, color: palette.white, fontFamily, fontSize: 26, fontWeight: 850}}>第 {String(chapter).padStart(2, '0')} 章</div></AbsoluteFill>; };

const Subtitles: React.FC = () => { const frame = useCurrentFrame(); const {fps} = useVideoConfig(); const seconds = frame / fps; const cue = timing.subtitleCues.find((item) => seconds >= item.from && seconds < item.from + item.duration) ?? timing.subtitleCues.at(-1); const text = cue?.text ?? ''; return <div style={{position: 'absolute', left: 94, right: 94, bottom: 30, minHeight: 78, background: palette.white, borderTop: `4px solid ${palette.ink}`, display: 'grid', gridTemplateColumns: '96px 1fr', alignItems: 'center', color: palette.ink, fontFamily}}><div style={{alignSelf: 'stretch', display: 'flex', alignItems: 'center', justifyContent: 'center', background: palette.red, color: palette.white, fontSize: 20, fontWeight: 850}}>VOICE</div><div style={{padding: '12px 30px', fontSize: text.length > 64 ? 24 : 28, lineHeight: 1.35, fontWeight: 750, textAlign: 'center'}}>{text}</div></div>; };

export const TransformerBeginnerLesson: React.FC<TransformerBeginnerLessonProps> = ({audio}) => { const {durationInFrames} = useVideoConfig(); const times = getTimings(durationInFrames); const progress = interpolate(useCurrentFrame(), [0, durationInFrames - 1], [0, 100], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}); return <AbsoluteFill style={{background: palette.paper}}><Audio src={staticFile(audio)} />{times.map(({section, from, duration}, index) => <Sequence key={section[0]} from={from} durationInFrames={duration}><LessonCard index={index} section={section} /></Sequence>)}{times.slice(1).map(({from}, index) => <Sequence key={from} from={from} durationInFrames={28}><Wipe chapter={index + 2} /></Sequence>)}<Subtitles /><div style={{position: 'absolute', top: 0, left: 0, right: 0, height: 8, background: palette.line}}><div style={{height: '100%', width: `${progress}%`, background: palette.teal}} /></div></AbsoluteFill>; };
