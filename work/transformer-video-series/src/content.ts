import type {Episode} from './types';

export const episodes: Episode[] = [
  {
    id: 'Transformer-01-Architecture',
    number: 1,
    title: 'Transformer 为什么改变了一切',
    shortTitle: '架构全景',
    accent: 'red',
    audio: 'audio/episode-01.neural.mp3',
    narrationTimings: [6.549479, 7.1875, 9.296875, 5.638021, 4.700521, 16.028646, 9.326957],
    narration:
      '在 Transformer 出现之前，处理语言最常见的方法是循环神经网络。它必须一个词接一个词地计算，前面的信息经过很长的路径才能传到后面。二零一七年，论文《Attention Is All You Need》换了一种思路：让序列中的每个位置直接观察其他所有位置。这样，模型既能并行训练，也能更容易捕捉远距离关系。一个标准 Transformer 由编码器和解码器组成。今天的大语言模型通常只保留解码器部分，但核心零件没有改变：注意力层负责交换信息，前馈网络负责独立思考，残差连接和归一化保证深层网络能够稳定训练。Transformer 真正重要的，不是某一个公式，而是它把语言理解变成了可以大规模并行的通用计算结构。',
    scenes: [
      {
        kind: 'overview',
        eyebrow: '01 / 架构全景',
        title: '一句话理解 Transformer',
        caption: '让每个位置直接观察整段序列。',
        weight: 1.0,
      },
      {
        kind: 'parallel',
        eyebrow: '旧方法',
        title: 'RNN：信息沿链条传递',
        caption: '路径越长，计算越慢，早期信息也更容易衰减。',
        weight: 1.25,
      },
      {
        kind: 'parallel',
        eyebrow: '新方法',
        title: 'Attention：所有位置并行通信',
        caption: '长距离关系只需要一次连接。',
        weight: 1.35,
      },
      {
        kind: 'block',
        eyebrow: '核心组件',
        title: '注意力 + 前馈网络',
        caption: '交换信息、处理信息，再通过残差连接稳定堆叠。',
        weight: 1.55,
      },
      {
        kind: 'outro',
        eyebrow: '下一集',
        title: '文字如何进入模型？',
        caption: 'Token、向量与位置信息。',
        weight: 0.65,
      },
    ],
  },
  {
    id: 'Transformer-02-Tokens',
    number: 2,
    title: 'Token、向量与位置编码',
    shortTitle: '输入表示',
    accent: 'cyan',
    audio: 'audio/episode-02.mp3',
    narration:
      '模型不能直接读取文字。第一步，是把句子切成 Token。Token 不一定等于一个完整单词，它可能是汉字、词片段，甚至标点。每个 Token 会通过一张可学习的查找表，变成一组数字，也就是词嵌入。相似概念在向量空间里往往靠得更近。但注意力本身没有顺序概念。如果把同一组词重新排列，它看到的内容几乎一样。因此，我们还要加入位置编码。原始 Transformer 使用正弦和余弦波，让每个位置拥有独特而连续的坐标；现代模型也常用旋转位置编码。最终送进网络的，不只是词的含义，而是词向量与位置信息的组合。模型就是从这组带坐标的向量开始理解句子。',
    scenes: [
      {
        kind: 'tokens',
        eyebrow: '02 / 输入表示',
        title: '句子先被切成 Token',
        caption: 'Token 可以是字、词片段或标点。',
        weight: 1.2,
      },
      {
        kind: 'tokens',
        eyebrow: 'Embedding',
        title: '离散符号变成连续向量',
        caption: '模型通过可学习的查找表获得语义坐标。',
        weight: 1.35,
      },
      {
        kind: 'positions',
        eyebrow: '问题',
        title: 'Attention 不知道先后顺序',
        caption: '“我爱你”和“你爱我”不能只看词集合。',
        weight: 1.15,
      },
      {
        kind: 'positions',
        eyebrow: 'Position',
        title: '为每个 Token 加入位置',
        caption: '语义向量加上位置坐标，顺序才进入模型。',
        weight: 1.55,
      },
      {
        kind: 'outro',
        eyebrow: '下一集',
        title: 'Self-Attention 如何计算？',
        caption: '从 Query、Key、Value 开始。',
        weight: 0.7,
      },
    ],
  },
  {
    id: 'Transformer-03-Attention',
    number: 3,
    title: 'Self-Attention 一步一步算',
    shortTitle: '注意力计算',
    accent: 'yellow',
    audio: 'audio/episode-03.mp3',
    narration:
      'Self-Attention 的目标，是让每个 Token 根据上下文重新组织自己的信息。模型先把每个输入向量分别投影成三份：Query、Key 和 Value。Query 表示我正在寻找什么，Key 表示我能提供什么线索，Value 则是真正要传递的内容。接下来，用一个 Query 与所有 Key 做点积。分数越高，代表两个位置越相关。分数除以向量维度的平方根，避免数值过大，再经过 Softmax，变成总和为一的注意力权重。最后，用这些权重对所有 Value 加权求和，就得到当前 Token 的新表示。例如在“动物没有过马路，因为它很累”中，“它”的 Query 会更关注“动物”的 Key，于是对应的 Value 会贡献更多信息。Self-Attention 本质上是一种可学习的动态信息路由。',
    scenes: [
      {
        kind: 'qkv',
        eyebrow: '03 / 注意力计算',
        title: '一份输入，三种角色',
        caption: 'Query 提问，Key 匹配，Value 传递内容。',
        weight: 1.25,
      },
      {
        kind: 'qkv',
        eyebrow: 'Step 1',
        title: 'Query 与所有 Key 做点积',
        caption: '相关性越强，得到的分数越高。',
        weight: 1.2,
      },
      {
        kind: 'matrix',
        eyebrow: 'Step 2',
        title: '缩放，再做 Softmax',
        caption: '分数被转换成总和为一的注意力权重。',
        weight: 1.25,
      },
      {
        kind: 'matrix',
        eyebrow: 'Step 3',
        title: '对 Value 加权求和',
        caption: '每个 Token 获得一份上下文化的新表示。',
        weight: 1.35,
      },
      {
        kind: 'overview',
        eyebrow: '本质',
        title: '动态信息路由',
        caption: '连接不是写死的，而是由当前内容实时计算。',
        weight: 1.1,
      },
      {
        kind: 'outro',
        eyebrow: '下一集',
        title: '为什么需要多个头？',
        caption: '不同关系，需要不同观察角度。',
        weight: 0.65,
      },
    ],
  },
  {
    id: 'Transformer-04-Block',
    number: 4,
    title: '从多头注意力到 Transformer Block',
    shortTitle: '核心模块',
    accent: 'red',
    audio: 'audio/episode-04.mp3',
    narration:
      '一次注意力计算只能在一个表示空间里观察关系。多头注意力会把向量切分成多个子空间，让不同的头同时学习不同模式：有的关注语法，有的追踪指代，有的寻找主题关联。各个头的结果拼接后，再经过一次线性变换。注意力层之后，是逐位置前馈网络。它对每个 Token 独立执行两层变换，扩展维度、激活，再压回原来的大小。注意力负责在 Token 之间交换信息，前馈网络负责处理每个位置收到的信息。每个子层外面都有残差连接，让原始信号可以直接绕过复杂变换；Layer Normalization 则控制数值分布。把这套结构重复堆叠几十层，模型就能逐步形成从局部词法到抽象语义的多层表示。',
    scenes: [
      {
        kind: 'heads',
        eyebrow: '04 / 核心模块',
        title: '多个头，同时观察',
        caption: '语法、指代、主题关系可以并行学习。',
        weight: 1.35,
      },
      {
        kind: 'heads',
        eyebrow: 'Merge',
        title: '拼接结果，再做线性变换',
        caption: '不同观察角度被重新融合。',
        weight: 1.05,
      },
      {
        kind: 'block',
        eyebrow: 'FFN',
        title: '每个位置独立思考',
        caption: '扩展、激活、压缩，提炼收到的信息。',
        weight: 1.25,
      },
      {
        kind: 'block',
        eyebrow: 'Stability',
        title: '残差连接 + LayerNorm',
        caption: '保留原始信号，让深层网络稳定训练。',
        weight: 1.35,
      },
      {
        kind: 'overview',
        eyebrow: 'Stack',
        title: '重复堆叠，逐层抽象',
        caption: '从词法关系，一步步走向抽象语义。',
        weight: 1.0,
      },
      {
        kind: 'outro',
        eyebrow: '下一集',
        title: '模型如何训练和生成？',
        caption: '预测下一个 Token，只是故事的开始。',
        weight: 0.65,
      },
    ],
  },
  {
    id: 'Transformer-05-Training',
    number: 5,
    title: '训练、生成与 KV Cache',
    shortTitle: '走向大模型',
    accent: 'cyan',
    audio: 'audio/episode-05.mp3',
    narration:
      '大语言模型最常见的训练目标非常简单：根据前面的 Token，预测下一个 Token。训练时，因果掩码会遮住未来位置，确保模型不能偷看答案。海量文本让模型反复完成这个任务，参数便逐渐吸收语言规律、知识关联和推理模式。生成时，过程变成串行循环：输入上下文，计算下一个 Token，把它接回序列，再预测下一步。为了避免每次都重新计算完整历史，推理系统会保存各层已经得到的 Key 和 Value，这就是 KV Cache。它用显存换速度，也是长上下文推理的重要成本来源。Transformer 的力量来自三个条件同时成立：结构可以并行，数据能够扩展，计算资源持续增长。从注意力公式到今天的大模型，中间并没有魔法，只有一套可以不断堆叠、训练和优化的工程体系。',
    scenes: [
      {
        kind: 'training',
        eyebrow: '05 / 训练与推理',
        title: '训练目标：预测下一个 Token',
        caption: '简单目标，在海量数据上产生复杂能力。',
        weight: 1.25,
      },
      {
        kind: 'mask',
        eyebrow: 'Causal Mask',
        title: '训练时不能偷看未来',
        caption: '每个位置只能观察自己和前面的内容。',
        weight: 1.2,
      },
      {
        kind: 'training',
        eyebrow: 'Generation',
        title: '生成是一个串行循环',
        caption: '预测、追加，再预测下一步。',
        weight: 1.1,
      },
      {
        kind: 'cache',
        eyebrow: 'KV Cache',
        title: '保存历史，避免重复计算',
        caption: '用显存换速度，长上下文也因此更昂贵。',
        weight: 1.35,
      },
      {
        kind: 'overview',
        eyebrow: 'Scale',
        title: '结构 × 数据 × 算力',
        caption: 'Transformer 让三者第一次高效地共同扩展。',
        weight: 1.1,
      },
      {
        kind: 'outro',
        eyebrow: '系列完结',
        title: '没有魔法，只有可扩展的工程',
        caption: '理解结构，才能真正理解大模型。',
        weight: 0.75,
      },
    ],
  },
];

export const getEpisode = (id: string) => {
  const episode = episodes.find((item) => item.id === id);
  if (!episode) {
    throw new Error(`Unknown episode: ${id}`);
  }
  return episode;
};
