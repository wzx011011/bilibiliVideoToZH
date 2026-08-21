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
  ArrowDown,
  ArrowRight,
  Box as BoxIcon,
  BrainCircuit,
  Database,
  Eye,
  Layers3,
  Network,
  ShieldAlert,
  Sparkles,
} from 'lucide-react';
import lessonTimingV2 from '../public/audio/transformer-beginner-10min-v2.neural.timing.json';
import lessonTimingV3 from '../public/audio/transformer-beginner-10min-v3.neural.timing.json';
import {fontFamily} from './theme';

export type TransformerBeginnerLessonV2Props = {
  audio: string;
  timingVersion?: 'v2' | 'v3';
  explainTerms?: boolean;
};

const C = {
  paper: '#f3f5f1',
  white: '#ffffff',
  ink: '#102a3a',
  muted: '#587078',
  line: '#cbd7d5',
  coral: '#eb4d52',
  teal: '#00a48e',
  yellow: '#f4c84b',
  navy: '#112832',
  paleCoral: '#f9dedf',
  paleTeal: '#d9f0eb',
  paleYellow: '#fff1bc',
} as const;

const chapters = [
  {eyebrow: '问题 / 上下文', title: '只改一个词，\n“它”就换了指代。', note: 'Transformer 要把符号变成表示，再从上下文取回有用信息。', visual: 'hook'},
  {eyebrow: '输入 / TOKEN + EMBEDDING', title: '文字先变编号，\n再变成向量。', note: 'Token 编号查询嵌入表，并与位置信息组合成模型输入。', visual: 'input'},
  {eyebrow: '路线 / SELF-ATTENTION', title: '不用逐站传话，\n但必须遵守可见范围。', note: '编码器能双向查看；GPT 的因果遮罩只能看左侧历史。', visual: 'mask'},
  {eyebrow: '机制 / Q · K · V', title: '同一份输入，\n并行生成三种表示。', note: 'Query 寻找线索，Key 参与匹配，Value 提供被汇总的信息。', visual: 'qkv'},
  {eyebrow: '计算 / SOFTMAX', title: '分数变权重，\n权重总和必须为 1。', note: '2.0、1.0、0.5 经 Softmax 后约为 63%、23%、14%。', visual: 'softmax'},
  {eyebrow: '积木 / TRANSFORMER BLOCK', title: '先交流，\n再各自加工。', note: '多头注意力、残差、归一化和前馈网络共同组成一层。', visual: 'block'},
  {eyebrow: '家族 / 三种结构', title: '同样的积木，\n不同的可见规则。', note: 'Encoder、Encoder-Decoder 和 Decoder-only 面向不同任务。', visual: 'family'},
  {eyebrow: '训练 / NEXT TOKEN', title: '答案来自数据，\n不是唯一合理的词。', note: '输入与目标错开一位，用交叉熵和反向传播更新参数。', visual: 'training'},
  {eyebrow: '生成 / SAMPLING + CACHE', title: '一次选择一枚 Token，\n历史计算可以复用。', note: '采样控制输出差异，KV Cache 用显存换生成速度。', visual: 'generation'},
  {eyebrow: '总结 / FOUR STEPS', title: '表示、匹配、汇总、预测。', note: '掌握这四步，就能看懂 Transformer 的核心信息流。', visual: 'recap'},
] as const;

type VisualKind = (typeof chapters)[number]['visual'];
type SubtitleCue = {text: string; from: number; duration: number};
type Timing = {paragraphDurations: number[]; subtitleCues: SubtitleCue[]};
type TermInfo = {
  term: string;
  english?: string;
  plain: string;
  why: string;
  example: string;
  color: string;
};
type VisualState = {focus: string; cueProgress: number; term: TermInfo | null};
const timingsByVersion: Record<'v2' | 'v3', Timing> = {
  v2: lessonTimingV2 as Timing,
  v3: lessonTimingV3 as Timing,
};

const splitSubtitle = (text: string, maxLength = 34) => {
  const clauses = text.match(/[^，。；：！？]+[，。；：！？]?/g) ?? [text];
  const chunks: string[] = [];
  let current = '';

  for (const clause of clauses) {
    if ((current + clause).length <= maxLength) {
      current += clause;
      continue;
    }
    if (current) chunks.push(current);
    current = clause;
    while (current.length > maxLength) {
      chunks.push(current.slice(0, maxLength));
      current = current.slice(maxLength);
    }
  }
  if (current) chunks.push(current);
  return chunks.length > 0 ? chunks : [text];
};

const enter = (frame: number, fps: number, delay = 0) =>
  spring({frame: Math.max(0, frame - delay), fps, config: {damping: 18, stiffness: 115, mass: 0.72}});

const chapterTimings = (durationInFrames: number, timing: Timing) => {
  const total = timing.paragraphDurations.reduce((sum, value) => sum + value, 0);
  let cursor = 0;
  return chapters.map((chapter, index) => {
    const duration = index === chapters.length - 1
      ? durationInFrames - cursor
      : Math.round((timing.paragraphDurations[index] / total) * durationInFrames);
    const result = {chapter, from: cursor, duration};
    cursor += duration;
    return result;
  });
};

const chapterStartSeconds = (index: number, timing: Timing) =>
  timing.paragraphDurations.slice(0, index).reduce((sum, value) => sum + value, 0);

const visualFocus = (kind: VisualKind, text: string) => {
  if (!text) return 'all';
  switch (kind) {
    case 'hook':
      if (/第二句|太小|指箱子/.test(text)) return 'box';
      if (/第一句|太大|指奖杯/.test(text)) return 'trophy';
      if (/只改|指代就变/.test(text)) return 'switch';
      return 'context';
    case 'input':
      if (/Tokenization|切成 Token|不一定|字、词片段/.test(text)) return 'tokens';
      if (/整数编号|编号只是索引/.test(text)) return 'ids';
      if (/嵌入表|Embedding|初始坐标|向量相同/.test(text)) return 'embedding';
      if (/位置|词序/.test(text)) return 'position';
      return 'final';
    case 'mask':
      if (/RNN|第一个位置|很多站|同时算完/.test(text)) return 'rnn';
      if (/Self-Attention|直接和其他位置/.test(text)) return 'attention';
      if (/编码器|双向/.test(text)) return 'encoder';
      if (/GPT|因果遮罩|未来答案/.test(text)) return 'gpt';
      return 'rule';
    case 'qkv':
      if (/点积|匹配分数|平方根/.test(text)) return 'score';
      if (/Softmax|旁边等待/.test(text)) return 'output';
      if (/Query 表示/.test(text)) return 'query';
      if (/Key 表示/.test(text)) return 'key';
      if (/Value 表示/.test(text)) return 'value';
      if (/同时|三次|不是先后|三种表示/.test(text)) return 'split';
      return 'input';
    case 'softmax':
      if (/玩具分数|二点零|一点零|零点五/.test(text)) return 'scores';
      if (/指数变换|Softmax 先/.test(text)) return 'transform';
      if (/百分之六十三|百分之百/.test(text)) return 'weights';
      if (/乘上|Value|结果相加|新向量|融合/.test(text)) return 'aggregate';
      if (/太小|箱子.*权重/.test(text)) return 'context';
      return 'note';
    case 'block':
      if (/一个注意力头|多个头|多种关系|职责/.test(text)) return 'attention';
      if (/拼接|输出投影/.test(text)) return 'attention';
      if (/残差|归一化/.test(text)) return 'residual';
      if (/前馈|非线性/.test(text)) return 'ffn';
      if (/交流|内部处理/.test(text)) return 'compare';
      return 'stack';
    case 'family':
      if (/原始论文|机器翻译|源句|目标句/.test(text)) return 'original';
      if (/BERT/.test(text)) return 'bert';
      if (/GPT|未来词|作弊/.test(text)) return 'gpt';
      return 'all';
    case 'training':
      if (/错开一位|之后预测|预训练目标/.test(text)) return 'shift';
      if (/监督信号|唯一合理/.test(text)) return 'target';
      if (/交叉熵|较高概率|目标是/.test(text)) return 'loss';
      if (/反向传播|优化器|更新参数/.test(text)) return 'backprop';
      if (/因果遮罩|同时计算/.test(text)) return 'parallel';
      return 'all';
    case 'generation':
      if (/Logits|概率分布|温度|Top-k|Top-p|采样/.test(text)) return 'sampling';
      if (/选出的 Token|追加|不等于汉字|词片段/.test(text)) return 'tokens';
      if (/Key 和 Value|KV Cache|新增 Token|读取缓存|显存/.test(text)) return 'cache';
      return 'tokens';
    case 'recap':
      if (/文字先切|嵌入|位置信息/.test(text)) return 'represent';
      if (/Query 和 Key|匹配分数/.test(text)) return 'match';
      if (/Softmax|Value|多头|前馈/.test(text)) return 'aggregate';
      if (/训练|生成|下一枚|KV Cache/.test(text)) return 'predict';
      if (/不等于|不能保证|编造|偏见/.test(text)) return 'warning';
      return 'all';
  }
};

const termForCue = (kind: VisualKind, text: string): TermInfo | null => {
  const term = (
    name: string,
    english: string,
    plain: string,
    why: string,
    example: string,
    color: string,
  ): TermInfo => ({term: name, english, plain, why, example, color});

  if (kind === 'hook' && /上下文，就是/.test(text)) {
    return term('上下文', 'CONTEXT', '当前位置周围、能帮助理解它的信息。', '后面的注意力，做的就是从上下文中挑选信息。', '“太大”让“它”更可能指向奖杯。', C.coral);
  }
  if (kind === 'input') {
    if (/便于处理的小块|叫作 Token/.test(text)) return term('Token', 'TOKEN', '模型一次处理的文字小块，不一定等于一个字或一个词。', '后面的向量、注意力和生成，都以 Token 为基本单位。', '“Transformer”可能被切成一个或多个 Token。', C.coral);
    if (/查表用的索引|图书馆的书号/.test(text)) return term('索引', 'INDEX', '用来定位资料的编号，编号本身不是资料内容。', '它解释了为什么 Token ID 不能直接代表语义。', '书号找到一本书；Token ID 找到一行嵌入向量。', C.yellow);
    if (/向量，就是|数字档案/.test(text)) return term('向量', 'VECTOR', '一列有固定顺序的数字，可以看成模型使用的数字档案。', 'Q、K、V、点积和每一层计算，处理的都是向量。', '“奖杯”可表示为 [0.21, -0.08, 0.44 …]。', C.teal);
    if (/每个数字叫一个维度|维度越多/.test(text)) return term('维度', 'DIMENSION', '向量中的一个数字位置，也就是档案中的一个特征槽位。', '后面点积会逐个维度对应相乘。', '三维向量 [2, 1, 3] 有三个数字槽位。', C.yellow);
    if (/这就是 Embedding|嵌入表可以理解/.test(text)) return term('嵌入', 'EMBEDDING', '把离散编号换成可训练向量的查表过程。', '文字必须先变成向量，才能进入神经网络计算。', 'Token ID #318 查表后得到一列数字。', C.teal);
  }
  if (kind === 'mask') {
    if (/Self-Attention，中文|所谓“自”/.test(text)) return term('自注意力', 'SELF-ATTENTION', '同一段输入里的位置互相比较，并分配不同重要程度。', '这是后面 Q、K、V 计算要实现的目标。', '“它”比较“奖杯”“箱子”和“太大”。', C.teal);
    if (/遮罩可以理解|访问权限表/.test(text)) return term('因果遮罩', 'CAUSAL MASK', '一张访问权限表，把尚未出现的未来位置挡住。', '它保证 GPT 训练时遵守生成顺序，不能偷看答案。', '预测“热”时，只能看到“今天天气很”。', C.coral);
  }
  if (kind === 'qkv') {
    if (/线性变换，可以|数字混合器/.test(text)) return term('线性变换', 'LINEAR TRANSFORM', '一台参数可调的数字混合器，把输入向量重新组合。', '同一输入经过三套混合器，才能分别得到 Q、K、V。', '同一份档案，分别提取“想找什么”和“能提供什么”。', C.yellow);
    if (/点积的算法|对应相乘/.test(text)) return term('点积', 'DOT PRODUCT', '两列数字对应相乘，再把所有乘积相加。', '注意力用它把 Query 与 Key 的相似程度压成一个分数。', '[2, 1] · [1, 3] = 2×1 + 1×3 = 5。', C.coral);
    if (/音量调回|维度多时/.test(text)) return term('缩放', 'SCALING', '把容易偏大的匹配分数调回合适范围。', '否则 Softmax 可能过早只盯住一个位置，训练不稳定。', 'Q·K 除以 √d，d 是 Key 的维度数。', C.yellow);
  }
  if (kind === 'softmax') {
    if (/Softmax 是一个|分数转权重/.test(text)) return term('Softmax', 'SOFTMAX', '把任意分数转换为一组正数比例，总和恰好为 100%。', '注意力需要用这些比例决定每个位置参考多少。', '2.0、1.0、0.5 → 63%、23%、14%。', C.coral);
    if (/这叫加权求和|重要的多取/.test(text)) return term('加权求和', 'WEIGHTED SUM', '重要信息乘较大比例，不重要信息乘较小比例，再相加。', '这是注意力真正把上下文汇入当前位置的一步。', '0.63×V奖杯 + 0.23×V箱子 + 0.14×V太大。', C.teal);
  }
  if (kind === 'block') {
    if (/一个注意力头，就是/.test(text)) return term('注意力头', 'ATTENTION HEAD', '一套独立的 Q、K、V 变换与匹配计算。', '多个头能让模型同时保留不同的观察角度。', '一个角度关注指代，另一个角度可能关注邻近搭配。', C.teal);
    if (/残差不是|一条捷径/.test(text)) return term('残差连接', 'RESIDUAL CONNECTION', '把处理前的输入沿捷径直接加回处理结果。', '层数很深时，它帮助保留原信息并让梯度更容易传递。', '输出 = 本层加工结果 + 本层原输入。', C.coral);
    if (/归一化再|稳定的尺度/.test(text)) return term('归一化', 'NORMALIZATION', '把一组数值调整到更稳定、可比较的尺度。', '它降低层与层之间数值忽大忽小带来的训练困难。', '像把不同音量的录音调到相近响度。', C.yellow);
    if (/前馈网络，简称|非线性意味着/.test(text)) return term('前馈网络', 'FFN', '每个位置独立使用的同一套小型加工网络。', '注意力取回信息后，还需要在当前位置内部组合和提炼。', '注意力负责“交流”，FFN 负责“消化”。', C.teal);
  }
  if (kind === 'family' && /编码器可以理解|解码器可以理解/.test(text)) {
    return term('编码器与解码器', 'ENCODER / DECODER', '编码器偏向读懂已有输入；解码器偏向按顺序写出新内容。', 'BERT、原始 Transformer 和 GPT 的结构差异由此展开。', '翻译时先读源句，再逐步写目标句。', C.yellow);
  }
  if (kind === 'training') {
    if (/数字叫参数|训练的目的/.test(text)) return term('参数', 'PARAMETER', '模型内部能被训练修改的大量数字。', '学到的语言规律最终都存进这些数字，而不是手写规则。', '一次训练只把许多参数各自微调一点。', C.yellow);
    if (/交叉熵可以|罚分表/.test(text)) return term('交叉熵', 'CROSS-ENTROPY', '一张按正确答案概率计算的罚分表。', '它把“预测得有多错”变成可优化的单个数值。', '正确词“热”的概率越低，罚分越高。', C.coral);
    if (/反向传播会|倒着追查/.test(text)) return term('反向传播', 'BACKPROPAGATION', '从最终罚分向前倒查每个参数对错误的影响。', '只有知道每个参数该往哪边改，模型才能学习。', '从“热”的罚分一路追到前面每一层参数。', C.teal);
    if (/优化器再|真正更新参数/.test(text)) return term('优化器', 'OPTIMIZER', '根据反向传播给出的方向和幅度更新参数的规则。', '反向传播负责算建议，优化器负责真正执行修改。', '像根据导航方向决定每一步实际走多远。', C.yellow);
  }
  if (kind === 'generation') {
    if (/原始分数，也叫 Logits|Logits 还不是概率/.test(text)) return term('Logits', 'LOGITS', '模型给词表中每个候选 Token 的原始分数，可正可负。', '它们必须先经过 Softmax，才能作为概率解释。', '“注意”可能得 4.2 分，“模型”得 3.1 分。', C.coral);
    if (/采样，也就是|随机性地抽取/.test(text)) return term('采样', 'SAMPLING', '按照概率从候选 Token 中抽取，而不总选第一名。', '它让相同提示可以产生不同但仍较合理的回答。', '62% 选“注意”，21% 选“模型”。', C.yellow);
    if (/温度控制|Top-k 只保留|Top-p 则保留/.test(text)) return term('采样参数', 'TEMPERATURE / TOP-K / TOP-P', '控制候选范围和概率分布形状的三个旋钮。', '它们共同调节输出的稳定程度与多样性。', '温度调分散度；Top-k 看名次；Top-p 看累计概率。', C.yellow);
    if (/Cache 就是缓存|临时工作台/.test(text)) return term('KV Cache', 'KEY-VALUE CACHE', '保存历史 Token 已算好的 Key 和 Value 的临时工作台。', '生成下一步时不必重算全部历史，因此速度更快。', '旧 K、V 直接读取，只计算新 Token 的 K、V。', C.teal);
    if (/显存是|显卡上/.test(text)) return term('显存', 'GPU MEMORY', '显卡上供模型高速读写的专用内存。', 'KV Cache 会放在这里，所以长上下文会增加显存占用。', '历史越长，需要保存的 K、V 数量越多。', C.coral);
  }
  return null;
};

const TermExplainer: React.FC<{info: TermInfo; progress: number}> = ({info, progress}) => {
  const reveal = interpolate(progress, [0, 0.12], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const cards = [
    ['白话含义', info.plain],
    ['为什么要懂', info.why],
    ['放回当前例子', info.example],
  ] as const;
  return (
    <div style={{position: 'absolute', inset: '72px 28px 28px', zIndex: 8, background: C.white, border: `4px solid ${info.color}`, boxShadow: `0 18px 46px ${info.color}26`, padding: '34px 38px', opacity: reveal, transform: `translateY(${(1 - reveal) * 20}px)`}}>
      <div style={{display: 'flex', alignItems: 'flex-end', gap: 20, borderBottom: `3px solid ${info.color}`, paddingBottom: 20}}>
        <div style={{fontSize: 18, fontWeight: 900, color: info.color}}>关键术语</div>
        <div style={{fontSize: 40, fontWeight: 950, lineHeight: 1}}>{info.term}</div>
        {info.english && <div style={{fontSize: 18, fontWeight: 850, color: C.muted, marginLeft: 'auto'}}>{info.english}</div>}
      </div>
      <div style={{display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginTop: 28}}>
        {cards.map(([label, value], index) => {
          const cardReveal = interpolate(progress, [0.06 + index * 0.08, 0.18 + index * 0.08], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
          return <div key={label} style={{minHeight: 255, background: index === 2 ? C.navy : C.paper, color: index === 2 ? C.white : C.ink, borderTop: `8px solid ${info.color}`, padding: '24px 22px', opacity: cardReveal, transform: `translateY(${(1 - cardReveal) * 16}px)`}}>
            <div style={{fontSize: 17, color: index === 2 ? info.color : C.muted, fontWeight: 900}}>{String(index + 1).padStart(2, '0')} / {label}</div>
            <div style={{fontSize: 24, lineHeight: 1.55, fontWeight: 800, marginTop: 22}}>{value}</div>
          </div>;
        })}
      </div>
      <div style={{position: 'absolute', left: 38, right: 38, bottom: 18, height: 6, background: C.line}}><div style={{height: '100%', width: `${progress * 100}%`, background: info.color}} /></div>
    </div>
  );
};

const FocusZone: React.FC<{
  active: boolean;
  dimmed?: boolean;
  progress: number;
  color?: string;
  children: React.ReactNode;
  style?: React.CSSProperties;
}> = ({active, dimmed = false, progress, color = C.coral, children, style}) => {
  const pulse = interpolate(progress, [0, 0.12, 0.55, 1], [0.35, 1, 0.55, 0.35], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <div style={{
      position: 'relative',
      opacity: dimmed && !active ? 0.36 : 1,
      filter: dimmed && !active ? 'saturate(0.55)' : 'none',
      transform: `scale(${active ? 1.018 : 1})`,
      transformOrigin: 'center',
      transition: 'opacity 180ms linear, filter 180ms linear',
      ...style,
    }}>
      {children}
      {active && <div style={{position: 'absolute', inset: -8, border: `4px solid ${color}`, boxShadow: `0 0 ${16 + pulse * 18}px ${color}55`, pointerEvents: 'none'}} />}
      {active && <div style={{position: 'absolute', right: -7, top: -30, background: color, color: color === C.yellow ? C.ink : C.white, padding: '5px 10px', fontSize: 15, fontWeight: 900}}>正在讲这里</div>}
    </div>
  );
};

const FlowDot: React.FC<{progress: number; color?: string}> = ({progress, color = C.teal}) => (
  <div style={{position: 'absolute', left: `${8 + progress * 84}%`, top: '50%', width: 14, height: 14, borderRadius: '50%', background: color, boxShadow: `0 0 18px ${color}`, transform: 'translate(-50%, -50%)'}} />
);

const Card: React.FC<{
  children: React.ReactNode;
  color?: string;
  dark?: boolean;
  delay?: number;
  style?: React.CSSProperties;
}> = ({children, color = C.teal, dark = false, delay = 0, style}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const visible = enter(frame, fps, delay);
  return (
    <div style={{
      background: dark ? C.navy : C.white,
      color: dark ? C.white : C.ink,
      border: `3px solid ${color}`,
      padding: '18px 20px',
      opacity: visible,
      transform: `translateY(${(1 - visible) * 18}px)`,
      ...style,
    }}>
      {children}
    </div>
  );
};

const Label: React.FC<{children: React.ReactNode; color?: string}> = ({children, color = C.muted}) => (
  <div style={{fontSize: 19, fontWeight: 850, color, lineHeight: 1.25}}>{children}</div>
);

const Arrow: React.FC<{color?: string; down?: boolean}> = ({color = C.teal, down = false}) =>
  down ? <ArrowDown size={34} color={color} strokeWidth={2.5} /> : <ArrowRight size={34} color={color} strokeWidth={2.5} />;

const Sentence: React.FC<{ending: '大' | '小'; active: '奖杯' | '箱子'; delay?: number}> = ({ending, active, delay = 0}) => (
  <Card color={ending === '大' ? C.coral : C.teal} delay={delay} style={{fontSize: 27, fontWeight: 800}}>
    <span style={{background: active === '奖杯' ? C.paleYellow : 'transparent', padding: '4px 7px'}}>奖杯</span>
    放不进
    <span style={{background: active === '箱子' ? C.paleYellow : 'transparent', padding: '4px 7px'}}>箱子</span>
    ，因为
    <span style={{color: C.coral}}>它</span>太{ending}。
  </Card>
);

const HookVisual: React.FC<VisualState> = ({focus, cueProgress}) => {
  const dimmed = focus !== 'context';
  return (
    <div style={{display: 'grid', gap: 22, padding: '112px 42px 40px'}}>
      <FocusZone active={focus === 'trophy'} dimmed={dimmed} progress={cueProgress} color={C.coral}><Sentence ending="大" active="奖杯" /></FocusZone>
      <FocusZone active={focus === 'box'} dimmed={dimmed} progress={cueProgress} color={C.teal}><Sentence ending="小" active="箱子" delay={8} /></FocusZone>
      <FocusZone active={focus === 'switch'} dimmed={dimmed} progress={cueProgress} color={C.yellow} style={{display: 'grid', gridTemplateColumns: '1fr 90px 1fr', alignItems: 'center', gap: 12, marginTop: 20}}>
        <Card color={C.coral} style={{textAlign: 'center'}}><Label color={C.coral}>“它” → 奖杯</Label></Card>
        <Arrow />
        <Card color={C.teal} style={{textAlign: 'center'}}><Label color={C.teal}>“它” → 箱子</Label></Card>
        {focus === 'switch' && <FlowDot progress={cueProgress} color={C.yellow} />}
      </FocusZone>
      <div style={{fontSize: 25, color: C.muted, textAlign: 'center'}}>最后一个词改变，整句中的关系也随之改变。</div>
    </div>
  );
};

const InputVisual: React.FC<VisualState> = ({focus, cueProgress}) => {
  const tokens = ['奖杯', '放', '不', '进', '箱子', '，', '因为', '它', '太大'];
  const dimmed = focus !== 'final';
  return (
    <div style={{padding: '105px 36px 36px'}}>
      <FocusZone active={focus === 'tokens'} dimmed={dimmed} progress={cueProgress} color={C.coral} style={{display: 'flex', gap: 8, justifyContent: 'center'}}>
        {tokens.map((token, index) => <Card key={token + index} delay={index * 3} color={index === 7 ? C.coral : C.teal} style={{padding: '13px 14px', fontSize: 22, fontWeight: 850}}>{token}</Card>)}
      </FocusZone>
      <div style={{display: 'flex', justifyContent: 'center', margin: '24px 0 18px'}}><Arrow down /></div>
      <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18}}>
        <FocusZone active={focus === 'ids'} dimmed={dimmed} progress={cueProgress} color={C.yellow}><Card color={C.yellow} delay={18}><Label color={C.ink}>TOKEN ID</Label><div style={{fontSize: 25, marginTop: 12, fontWeight: 850}}>#318 · #76 · #904 ...</div><div style={{fontSize: 18, color: C.muted, marginTop: 8}}>只是查表索引</div></Card></FocusZone>
        <FocusZone active={focus === 'embedding'} dimmed={dimmed} progress={cueProgress} color={C.teal}><Card color={C.teal} delay={24}><Label color={C.ink}>TOKEN EMBEDDING</Label><div style={{fontSize: 25, marginTop: 12, fontWeight: 850}}>[0.21, -0.08, 0.44 ...]</div><div style={{fontSize: 18, color: C.muted, marginTop: 8}}>可训练的初始坐标</div></Card></FocusZone>
      </div>
      <div style={{display: 'flex', justifyContent: 'center', margin: '18px 0 12px'}}><Arrow down /></div>
      <FocusZone active={focus === 'position' || focus === 'final'} dimmed={false} progress={cueProgress} color={C.coral}><Card color={C.coral} delay={30} style={{textAlign: 'center', fontSize: 25, fontWeight: 850}}>Token Embedding <span style={{color: C.coral}}>+</span> Position → 带顺序的向量序列</Card></FocusZone>
    </div>
  );
};

const Matrix: React.FC<{causal?: boolean; delay?: number}> = ({causal = false, delay = 0}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const visible = enter(frame, fps, delay);
  return (
    <div style={{display: 'grid', gridTemplateColumns: 'repeat(5, 42px)', gap: 5, opacity: visible}}>
      {Array.from({length: 25}, (_, index) => {
        const row = Math.floor(index / 5);
        const col = index % 5;
        const allowed = !causal || col <= row;
        return <div key={index} style={{height: 42, background: allowed ? (row === col ? C.coral : C.teal) : C.line, opacity: allowed ? 0.9 : 0.42, display: 'grid', placeItems: 'center', color: C.white, fontSize: 16, fontWeight: 850}}>{allowed ? '✓' : '×'}</div>;
      })}
    </div>
  );
};

const MaskVisual: React.FC<VisualState> = ({focus, cueProgress}) => (
  <div style={{padding: '105px 48px 36px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 46}}>
    <FocusZone active={focus === 'encoder'} dimmed={focus === 'gpt'} progress={cueProgress} color={C.teal}>
      <Label color={C.teal}>ENCODER / 双向</Label>
      <div style={{fontSize: 22, color: C.muted, margin: '10px 0 20px'}}>每个位置可看左右完整输入</div>
      <Matrix />
    </FocusZone>
    <FocusZone active={focus === 'gpt'} dimmed={focus === 'encoder'} progress={cueProgress} color={C.coral}>
      <Label color={C.coral}>GPT / 因果遮罩</Label>
      <div style={{fontSize: 22, color: C.muted, margin: '10px 0 20px'}}>只能看自己与左侧历史</div>
      <Matrix causal delay={10} />
    </FocusZone>
    <FocusZone active={focus === 'rule' || focus === 'attention' || focus === 'rnn'} dimmed={false} progress={cueProgress} color={C.yellow} style={{gridColumn: '1 / -1'}}><Card color={C.yellow} delay={20} style={{textAlign: 'center', fontSize: 25, fontWeight: 850}}>{focus === 'rnn' ? 'RNN：信息沿链条逐站传递。' : focus === 'attention' ? 'Self-Attention：允许的位置可以直接比较。' : '准确说法：查看规则允许访问的上下文。'}</Card></FocusZone>
  </div>
);

const QkvVisual: React.FC<VisualState> = ({focus, cueProgress}) => (
  <div style={{padding: '102px 42px 36px'}}>
    <FocusZone active={focus === 'input' || focus === 'split'} dimmed={false} progress={cueProgress} color={C.navy} style={{width: 300, margin: '0 auto'}}><Card color={C.navy} dark style={{textAlign: 'center'}}>
      <Label color={C.white}>同一个输入向量 x</Label>
    </Card></FocusZone>
    <div style={{height: 64, position: 'relative'}}>
      <div style={{position: 'absolute', left: '50%', top: 0, width: 3, height: 25, background: C.navy}} />
      <div style={{position: 'absolute', left: '20%', right: '20%', top: 25, height: 3, background: C.navy}} />
      {[20, 50, 80].map((left) => <div key={left} style={{position: 'absolute', left: `${left}%`, top: 25, width: 3, height: 38, background: C.navy}} />)}
      {focus === 'split' && <FlowDot progress={cueProgress} color={C.yellow} />}
    </div>
    <div style={{display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 18}}>
      {[
        ['Q = xWQ', '正在找什么？', C.coral],
        ['K = xWK', '提供什么线索？', C.yellow],
        ['V = xWV', '真正取回什么？', C.teal],
      ].map(([title, note, color], index) => (
        <FocusZone key={title} active={focus === ['query', 'key', 'value'][index] || focus === 'split'} dimmed={['query', 'key', 'value'].includes(focus)} progress={cueProgress} color={color}>
        <Card color={color} delay={index * 8 + 8} style={{textAlign: 'center'}}>
          <div style={{fontSize: 27, fontWeight: 900}}>{title}</div>
          <div style={{fontSize: 20, color: C.muted, marginTop: 12}}>{note}</div>
        </Card>
        </FocusZone>
      ))}
    </div>
    <div style={{display: 'grid', gridTemplateColumns: '1fr 64px 1fr', gap: 14, alignItems: 'center', marginTop: 30}}>
      <FocusZone active={focus === 'score'} dimmed={focus === 'output'} progress={cueProgress} color={C.coral}><Card color={C.coral} delay={32} style={{textAlign: 'center'}}><Label>Q · K / √d</Label><div style={{fontSize: 19, marginTop: 7}}>得到匹配分数</div></Card></FocusZone>
      <div style={{position: 'relative'}}><Arrow />{(focus === 'score' || focus === 'output') && <FlowDot progress={cueProgress} />}</div>
      <FocusZone active={focus === 'output'} dimmed={focus === 'score'} progress={cueProgress} color={C.teal}><Card color={C.teal} delay={38} style={{textAlign: 'center'}}><Label>Softmax × V</Label><div style={{fontSize: 19, marginTop: 7}}>汇总上下文信息</div></Card></FocusZone>
    </div>
  </div>
);

const SoftmaxVisual: React.FC<VisualState> = ({focus, cueProgress}) => {
  const bars = [
    {label: '奖杯', score: '2.0', pct: 63, color: C.coral},
    {label: '箱子', score: '1.0', pct: 23, color: C.teal},
    {label: '太大', score: '0.5', pct: 14, color: C.yellow},
  ];
  return (
    <div style={{padding: '104px 44px 36px'}}>
      <div style={{display: 'grid', gridTemplateColumns: '1fr 100px 1.2fr', alignItems: 'center', gap: 18}}>
        <FocusZone active={focus === 'scores'} dimmed={['weights', 'aggregate'].includes(focus)} progress={cueProgress} color={C.coral} style={{display: 'grid', gap: 14}}>
          {bars.map((bar, index) => <Card key={bar.label} color={bar.color} delay={index * 5}><div style={{display: 'flex', justifyContent: 'space-between', fontSize: 24, fontWeight: 850}}><span>{bar.label}</span><span>{bar.score}</span></div></Card>)}
        </FocusZone>
        <FocusZone active={focus === 'transform'} dimmed={false} progress={cueProgress} color={C.yellow} style={{textAlign: 'center'}}><Arrow /><div style={{fontSize: 17, color: C.muted, marginTop: 10}}>SOFTMAX</div>{focus === 'transform' && <FlowDot progress={cueProgress} color={C.yellow} />}</FocusZone>
        <FocusZone active={focus === 'weights' || focus === 'context'} dimmed={focus === 'scores'} progress={cueProgress} color={focus === 'context' ? C.teal : C.coral} style={{display: 'grid', gap: 18}}>
          {bars.map((bar, index) => <div key={bar.label} style={{display: 'grid', gridTemplateColumns: '72px 1fr 60px', alignItems: 'center', gap: 12}}>
            <Label color={C.ink}>{bar.label}</Label>
            <div style={{height: 38, background: C.paper, border: `1px solid ${C.line}`}}><div style={{height: '100%', width: `${bar.pct}%`, background: bar.color, transformOrigin: 'left', transform: `scaleX(${enter(useCurrentFrame(), useVideoConfig().fps, 12 + index * 6)})`}} /></div>
            <Label color={bar.color}>{bar.pct}%</Label>
          </div>)}
        </FocusZone>
      </div>
      <FocusZone active={focus === 'weights'} dimmed={false} progress={cueProgress} color={C.navy} style={{marginTop: 35}}><Card color={C.navy} dark delay={32} style={{textAlign: 'center', fontSize: 28, fontWeight: 900}}>63% + 23% + 14% = 100%</Card></FocusZone>
      <FocusZone active={focus === 'aggregate'} dimmed={false} progress={cueProgress} color={C.teal} style={{marginTop: 23}}><div style={{textAlign: 'center', fontSize: 24, color: C.muted}}>新表示 = 0.63 V奖杯 + 0.23 V箱子 + 0.14 V太大</div></FocusZone>
    </div>
  );
};

const BlockVisual: React.FC<VisualState> = ({focus, cueProgress}) => {
  const steps = [
    ['输入向量', C.yellow, BoxIcon],
    ['多头注意力', C.teal, Network],
    ['残差 + 归一化', C.coral, Layers3],
    ['前馈网络 FFN', C.teal, BrainCircuit],
    ['残差 + 归一化', C.coral, Layers3],
  ] as const;
  return (
    <div style={{padding: '82px 105px 24px', display: 'grid', gap: 7}}>
      {steps.map(([label, color, Icon], index) => (
        <React.Fragment key={label + index}>
          <FocusZone active={(focus === 'attention' && index === 1) || (focus === 'residual' && (index === 2 || index === 4)) || (focus === 'ffn' && index === 3) || (focus === 'compare' && (index === 1 || index === 3))} dimmed={['attention', 'residual', 'ffn', 'compare'].includes(focus)} progress={cueProgress} color={color}>
          <Card color={color} delay={index * 7} style={{height: 66, display: 'flex', alignItems: 'center', gap: 20, padding: '10px 22px'}}>
            <Icon size={31} color={color} /><span style={{fontSize: 25, fontWeight: 900}}>{label}</span>
            <span style={{marginLeft: 'auto', color: C.muted, fontSize: 19}}>{index === 1 ? '位置之间交流' : index === 3 ? '每个位置独立加工' : ''}</span>
          </Card>
          </FocusZone>
          {index < steps.length - 1 && <div style={{display: 'flex', justifyContent: 'center', height: 24}}><Arrow down color={C.line} /></div>}
        </React.Fragment>
      ))}
    </div>
  );
};

const FamilyVisual: React.FC<VisualState> = ({focus, cueProgress}) => (
  <div style={{padding: '105px 36px 36px', display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 17}}>
    {[
      ['BERT 类', 'ENCODER', '双向查看输入', '理解 / 分类 / 抽取', C.teal],
      ['原始 Transformer', 'ENCODER → DECODER', '读源句，再生成目标句', '翻译 / 转换', C.yellow],
      ['GPT 类', 'DECODER-ONLY', '因果遮罩，只看历史', '续写 / 对话 / 代码', C.coral],
    ].map(([name, kind, rule, use, color], index) => (
      <FocusZone key={name} active={focus === ['bert', 'original', 'gpt'][index]} dimmed={focus !== 'all'} progress={cueProgress} color={color}>
      <Card color={color} delay={index * 8} style={{minHeight: 360, display: 'flex', flexDirection: 'column'}}>
        <Label color={color}>{kind}</Label>
        <div style={{fontSize: 29, fontWeight: 900, marginTop: 18}}>{name}</div>
        <div style={{height: 3, background: color, margin: '24px 0'}} />
        <div style={{fontSize: 22, lineHeight: 1.45}}>{rule}</div>
        <div style={{marginTop: 'auto', padding: '15px', background: C.paper, fontSize: 20, fontWeight: 800}}>{use}</div>
      </Card>
      </FocusZone>
    ))}
  </div>
);

const TrainingVisual: React.FC<VisualState> = ({focus, cueProgress}) => {
  const sequence = ['今天', '天气', '很', '热'];
  return (
    <div style={{padding: '98px 42px 36px'}}>
      <Label color={C.teal}>输入与目标错开一位</Label>
      <FocusZone active={focus === 'shift' || focus === 'target' || focus === 'parallel'} dimmed={['loss', 'backprop'].includes(focus)} progress={cueProgress} color={focus === 'target' ? C.coral : C.teal} style={{display: 'grid', gridTemplateColumns: '110px repeat(4, 1fr)', gap: 10, marginTop: 20, alignItems: 'center'}}>
        <Label>输入</Label>{sequence.map((token, index) => <Card key={'i' + token} color={C.teal} delay={index * 4} style={{padding: 14, textAlign: 'center', fontSize: 24, fontWeight: 850}}>{token}</Card>)}
        <Label>目标</Label>{[...sequence.slice(1), '〈结束〉'].map((token, index) => <Card key={'t' + token} color={C.coral} delay={index * 4 + 9} style={{padding: 14, textAlign: 'center', fontSize: 24, fontWeight: 850}}>{token}</Card>)}
      </FocusZone>
      <div style={{display: 'grid', gridTemplateColumns: '1fr 68px 1fr 68px 1fr', gap: 10, alignItems: 'center', marginTop: 38}}>
        <FocusZone active={focus === 'loss'} dimmed={focus === 'backprop'} progress={cueProgress} color={C.yellow}><Card color={C.yellow} delay={28} style={{textAlign: 'center'}}><Label>概率分布</Label><div style={{fontSize: 19, marginTop: 8}}>“很”后：热 0.31</div></Card></FocusZone>
        <Arrow />
        <FocusZone active={focus === 'loss'} dimmed={focus === 'backprop'} progress={cueProgress} color={C.coral}><Card color={C.coral} delay={34} style={{textAlign: 'center'}}><Label>交叉熵损失</Label><div style={{fontSize: 19, marginTop: 8}}>目标是数据中的“热”</div></Card></FocusZone>
        <Arrow />
        <FocusZone active={focus === 'backprop'} dimmed={focus === 'loss'} progress={cueProgress} color={C.teal}><Card color={C.teal} delay={40} style={{textAlign: 'center'}}><Label>反向传播</Label><div style={{fontSize: 19, marginTop: 8}}>微调全部参数</div></Card></FocusZone>
      </div>
      <div style={{fontSize: 22, color: C.muted, textAlign: 'center', marginTop: 27}}>“冷”也可能通顺，但这一条训练样本的监督信号是“热”。</div>
    </div>
  );
};

const GenerationVisual: React.FC<VisualState> = ({focus, cueProgress}) => {
  const frame = useCurrentFrame();
  const shown = Math.min(5, Math.floor(frame / 22) + 1);
  const tokens = ['注意', '力', '让', '信息', '交流'];
  return (
    <div style={{padding: '98px 40px 34px'}}>
      <Label color={C.coral}>逐 TOKEN 生成</Label>
      <FocusZone active={focus === 'tokens'} dimmed={focus === 'cache'} progress={cueProgress} color={C.coral} style={{display: 'flex', gap: 11, alignItems: 'center', minHeight: 95, marginTop: 18}}>
        <Card color={C.navy} dark style={{fontSize: 22, fontWeight: 850}}>Transformer 的核心是</Card>
        {tokens.slice(0, shown).map((token, index) => <Card key={token + index} color={index === shown - 1 ? C.coral : C.teal} delay={0} style={{padding: '14px 16px', fontSize: 23, fontWeight: 900}}>{token}</Card>)}
      </FocusZone>
      <div style={{display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: 20, marginTop: 34}}>
        <FocusZone active={focus === 'sampling'} dimmed={focus === 'cache'} progress={cueProgress} color={C.yellow}><Card color={C.yellow} delay={15}>
          <Label color={C.ink}>采样选择</Label>
          <div style={{display: 'grid', gap: 12, marginTop: 18}}>
            {[['注意', 62], ['模型', 21], ['计算', 11]].map(([label, pct]) => <div key={String(label)} style={{display: 'grid', gridTemplateColumns: '64px 1fr 45px', gap: 10, alignItems: 'center'}}><span>{label}</span><div style={{height: 20, background: C.paper}}><div style={{height: '100%', width: `${pct}%`, background: C.yellow}} /></div><span>{pct}%</span></div>)}
          </div>
        </Card></FocusZone>
        <FocusZone active={focus === 'cache'} dimmed={focus === 'sampling'} progress={cueProgress} color={C.teal}><Card color={C.teal} delay={23}>
          <Database size={43} color={C.teal} />
          <div style={{fontSize: 27, fontWeight: 900, marginTop: 14}}>KV CACHE</div>
          <div style={{fontSize: 20, color: C.muted, lineHeight: 1.5, marginTop: 10}}>保存历史 K、V<br />新一步只计算新增部分</div>
        </Card></FocusZone>
      </div>
      <div style={{fontSize: 22, color: C.muted, textAlign: 'center', marginTop: 26}}>更快生成，但更长上下文会占用更多显存。</div>
    </div>
  );
};

const RecapVisual: React.FC<VisualState> = ({focus, cueProgress}) => {
  const items = [
    ['01', '表示', '文字 → Token → 向量', C.coral],
    ['02', '匹配', 'Query 与 Key 比较', C.yellow],
    ['03', '汇总', 'Softmax 权重 × Value', C.teal],
    ['04', '预测', '选择下一枚 Token', C.navy],
  ] as const;
  return (
    <div style={{padding: '98px 42px 36px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18}}>
      {items.map(([number, title, note, color], index) => (
        <FocusZone key={title} active={focus === ['represent', 'match', 'aggregate', 'predict'][index]} dimmed={!['all', 'warning'].includes(focus)} progress={cueProgress} color={color}><Card color={color} dark={color === C.navy} delay={index * 8} style={{height: 170, display: 'grid', gridTemplateColumns: '75px 1fr', alignItems: 'center', gap: 18}}>
          <div style={{fontSize: 42, fontWeight: 950, color}}>{number}</div>
          <div><div style={{fontSize: 30, fontWeight: 950}}>{title}</div><div style={{fontSize: 20, color: color === C.navy ? '#d6e1de' : C.muted, marginTop: 10}}>{note}</div></div>
        </Card></FocusZone>
      ))}
      <FocusZone active={focus === 'warning'} dimmed={false} progress={cueProgress} color={C.coral} style={{gridColumn: '1 / -1'}}><div style={{display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 16, fontSize: 23, fontWeight: 850, color: C.muted}}><ShieldAlert size={34} color={C.coral} />强大的概率模型，不等于永远正确。</div></FocusZone>
    </div>
  );
};

const Visual: React.FC<{kind: VisualKind; state: VisualState}> = ({kind, state}) => {
  let content: React.ReactNode;
  switch (kind) {
    case 'hook': content = <HookVisual {...state} />; break;
    case 'input': content = <InputVisual {...state} />; break;
    case 'mask': content = <MaskVisual {...state} />; break;
    case 'qkv': content = <QkvVisual {...state} />; break;
    case 'softmax': content = <SoftmaxVisual {...state} />; break;
    case 'block': content = <BlockVisual {...state} />; break;
    case 'family': content = <FamilyVisual {...state} />; break;
    case 'training': content = <TrainingVisual {...state} />; break;
    case 'generation': content = <GenerationVisual {...state} />; break;
    case 'recap': content = <RecapVisual {...state} />; break;
  }
  return <>{content}{state.term && <TermExplainer key={`${state.term.term}-${state.term.english ?? ''}`} info={state.term} progress={state.cueProgress} />}</>;
};

const Chapter: React.FC<{
  index: number;
  chapter: (typeof chapters)[number];
  timing: Timing;
  explainTerms: boolean;
}> = ({index, chapter, timing, explainTerms}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const absoluteSeconds = chapterStartSeconds(index, timing) + frame / fps;
  const cue = timing.subtitleCues.find((item) => absoluteSeconds >= item.from && absoluteSeconds < item.from + item.duration);
  const cueProgress = cue ? Math.min(1, Math.max(0, (absoluteSeconds - cue.from) / cue.duration)) : 0;
  const cueText = cue?.text ?? '';
  const state: VisualState = {
    focus: visualFocus(chapter.visual, cueText),
    cueProgress,
    term: explainTerms ? termForCue(chapter.visual, cueText) : null,
  };
  const visible = enter(frame, fps);
  const opacity = interpolate(frame, [durationInFrames - 14, durationInFrames], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <AbsoluteFill style={{background: C.paper, color: C.ink, fontFamily, opacity, overflow: 'hidden'}}>
      <div style={{position: 'absolute', inset: 0, opacity: 0.55, backgroundImage: 'linear-gradient(to right, transparent 0, transparent 239px, rgba(16,42,58,0.05) 240px, transparent 241px), linear-gradient(to bottom, transparent 0, transparent 179px, rgba(16,42,58,0.05) 180px, transparent 181px)', backgroundSize: '240px 180px'}} />
      <div style={{position: 'absolute', left: 0, top: 0, bottom: 0, width: 28, background: C.coral}} />
      <header style={{position: 'absolute', top: 42, left: 74, right: 74, display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 20, fontWeight: 850}}>
        <div><span style={{color: C.coral}}>TRANSFORMER / FROM ZERO</span><span style={{margin: '0 16px'}}>---</span><span style={{color: C.muted}}>REFINED LESSON</span></div>
        <div style={{color: C.muted}}>第 {String(index + 1).padStart(2, '0')} / {String(chapters.length).padStart(2, '0')} 章</div>
      </header>
      <section style={{position: 'absolute', left: 94, top: 140, width: 685, opacity: visible, transform: `translateY(${(1 - visible) * 28}px)`}}>
        <div style={{fontSize: 23, color: C.teal, fontWeight: 900}}><span style={{display: 'inline-block', width: 12, height: 12, background: C.teal, marginRight: 12}} />{chapter.eyebrow}</div>
        <h1 style={{fontSize: chapter.title.length > 20 ? 60 : 67, whiteSpace: 'pre-line', lineHeight: 1.14, margin: '28px 0 23px', letterSpacing: 0}}>{chapter.title}</h1>
        <p style={{fontSize: 27, lineHeight: 1.55, color: C.muted, margin: 0, maxWidth: 625}}>{chapter.note}</p>
        <div style={{display: 'flex', alignItems: 'center', gap: 13, marginTop: 52, color: C.muted, fontSize: 19, fontWeight: 800}}><Sparkles size={25} color={C.yellow} /> ONE IDEA, FULLY EXPLAINED</div>
      </section>
      <section style={{position: 'absolute', left: 850, right: 78, top: 142, bottom: 176, background: C.white, border: `2px solid ${C.ink}`, opacity: visible, transform: `translateX(${(1 - visible) * 38}px)`, overflow: 'hidden'}}>
        <div style={{position: 'absolute', left: 31, top: 25, fontSize: 18, fontWeight: 900, color: C.muted}}>CHAPTER VISUAL / {String(index + 1).padStart(2, '0')}</div>
        <Visual kind={chapter.visual} state={state} />
      </section>
      <div style={{position: 'absolute', left: 94, right: 94, bottom: 132, height: 1, background: C.line}} />
      <div style={{position: 'absolute', left: 94, bottom: 151, display: 'flex', gap: 8}}>{chapters.map((_, dot) => <div key={dot} style={{width: dot === index ? 38 : 9, height: 6, background: dot === index ? C.coral : C.line}} />)}</div>
    </AbsoluteFill>
  );
};

const Subtitles: React.FC<{timing: Timing}> = ({timing}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const seconds = frame / fps;
  const cue = timing.subtitleCues.find((item) => seconds >= item.from && seconds < item.from + item.duration);
  const chunks = splitSubtitle(cue?.text ?? '');
  const totalCharacters = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const elapsed = cue ? seconds - cue.from : 0;
  let cursor = 0;
  const text = chunks.find((chunk) => {
    cursor += cue && totalCharacters > 0 ? cue.duration * (chunk.length / totalCharacters) : 0;
    return elapsed < cursor;
  }) ?? chunks.at(-1) ?? '';
  return (
    <div style={{position: 'absolute', left: 94, right: 94, bottom: 28, height: 92, background: C.white, borderTop: `4px solid ${C.ink}`, display: 'grid', gridTemplateColumns: '96px 1fr', alignItems: 'center', color: C.ink, fontFamily}}>
      <div style={{alignSelf: 'stretch', display: 'grid', placeItems: 'center', background: C.coral, color: C.white, fontSize: 18, fontWeight: 900}}>VOICE</div>
      <div style={{padding: '10px 28px', fontSize: text.length > 30 ? 25 : 27, lineHeight: 1.35, fontWeight: 780, textAlign: 'center'}}>{text}</div>
    </div>
  );
};

const Wipe: React.FC<{index: number}> = ({index}) => {
  const frame = useCurrentFrame();
  const move = interpolate(frame, [0, 8, 17, 26], [-120, 0, 0, 128], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <AbsoluteFill style={{overflow: 'hidden'}}>
      {[C.coral, C.navy, C.teal, C.yellow].map((color, stripe) => <div key={color} style={{position: 'absolute', top: 0, bottom: 0, left: `${stripe * 25 - 27}%`, width: '32%', background: color, transform: `translateX(${move + stripe * 8}px) skewX(-12deg)`}} />)}
      <div style={{position: 'absolute', left: 80, bottom: 84, color: C.white, fontFamily, fontWeight: 900, fontSize: 24}}>CHAPTER {String(index).padStart(2, '0')}</div>
    </AbsoluteFill>
  );
};

export const TransformerBeginnerLessonV2: React.FC<TransformerBeginnerLessonV2Props> = ({
  audio,
  timingVersion = 'v2',
  explainTerms = false,
}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const timing = timingsByVersion[timingVersion];
  const timings = chapterTimings(durationInFrames, timing);
  const progress = interpolate(frame, [0, durationInFrames - 1], [0, 100], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <AbsoluteFill style={{background: C.paper}}>
      <Audio src={staticFile(audio)} />
      {timings.map(({chapter, from, duration}, index) => <Sequence key={chapter.visual} from={from} durationInFrames={duration}><Chapter index={index} chapter={chapter} timing={timing} explainTerms={explainTerms} /></Sequence>)}
      {timings.slice(1).map(({from}, index) => <Sequence key={from} from={from} durationInFrames={27}><Wipe index={index + 2} /></Sequence>)}
      <Subtitles timing={timing} />
      <div style={{position: 'absolute', top: 0, left: 0, right: 0, height: 8, background: C.line}}><div style={{height: '100%', width: `${progress}%`, background: C.teal}} /></div>
    </AbsoluteFill>
  );
};
