import {
  AbsoluteFill,
  Audio,
  Img,
  Sequence,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
} from "remotion";

export interface Chapter {
  id: number;
  speaker: string;
  speakerName: string;
  avatarFile?: string;
  start: number;
  end: number;
  text: string;
  audioFile: string;
}

interface PodcastProps {
  title: string;
  chapters: Chapter[];
  /** 分块渲染窗口(帧):只挂载窗口±100s 内的音频序列,防章节过多初始渲染超时 */
  renderWindow?: { from: number; to: number };
}

/* ─── 动画背景 ─── */
const AnimatedBackground: React.FC<{ hue: number }> = ({ hue }) => {
  const frame = useCurrentFrame();
  const y1 = interpolate(frame, [0, 300], [0, -100], {
    extrapolateRight: "clamp",
  });
  const y2 = interpolate(frame, [0, 300], [100, 0], {
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill>
      <div
        style={{
          width: "100%",
          height: "100%",
          background: `linear-gradient(135deg,
            hsl(${hue}, 60%, 8%) 0%,
            hsl(${hue + 20}, 50%, 12%) 50%,
            hsl(${hue - 10}, 40%, 6%) 100%)`,
        }}
      />
      <div
        style={{
          position: "absolute",
          width: 600,
          height: 600,
          borderRadius: "50%",
          background: `radial-gradient(circle, hsla(${hue},80%,50%,0.08) 0%, transparent 70%)`,
          top: y1,
          left: -100,
        }}
      />
      <div
        style={{
          position: "absolute",
          width: 500,
          height: 500,
          borderRadius: "50%",
          background: `radial-gradient(circle, hsla(${hue + 60},70%,40%,0.06) 0%, transparent 70%)`,
          bottom: y2,
          right: -50,
        }}
      />
    </AbsoluteFill>
  );
};

/* ─── 说话人真人头像 ─── */
const SpeakerAvatar: React.FC<{
  name: string;
  active: boolean;
  color: string;
  avatarFile?: string;
}> = ({ name, active, color, avatarFile }) => {
  const frame = useCurrentFrame();
  const scale = active
    ? spring({ frame, fps: 30, config: { damping: 12 }, from: 0.8, to: 1 })
    : 0.85;

  const common: React.CSSProperties = {
    width: 230,
    height: 230,
    borderRadius: "50%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: 52,
    fontWeight: 700,
    fontFamily: "Microsoft YaHei",
    color: active ? "#fff" : "rgba(255,255,255,0.3)",
    border: active ? `6px solid ${color}` : "6px solid rgba(255,255,255,0.1)",
    transform: `scale(${scale})`,
    boxShadow: active ? `0 0 50px ${color}44` : "none",
    objectFit: "cover",
    background: active
      ? `linear-gradient(135deg, ${color}, ${color}99)`
      : "rgba(255,255,255,0.06)",
    overflow: "hidden",
  };

  if (avatarFile) {
    return (
      <div style={{ ...common, padding: 0 }}>
        <Img
          src={staticFile(avatarFile)}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            borderRadius: "50%",
          }}
        />
      </div>
    );
  }

  const initials = name
    .split(" ")
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  return <div style={common}>{initials}</div>;
};

/* ─── 字幕:按句切条,随播放时间推进(每条 ≤32 字单行,时长按字数分摊) ─── */
const MAX_CUE_CHARS = 32;

const splitCues = (text: string): string[] => {
  const parts = text
    .split(/(?<=[。？！；])/)
    .map((s) => s.trim())
    .filter(Boolean);
  const pieces: string[] = [];
  for (const p of parts) {
    if (p.length <= MAX_CUE_CHARS) {
      pieces.push(p);
      continue;
    }
    const subs = p
      .split(/(?<=[，、：])/)
      .map((s) => s.trim())
      .filter(Boolean);
    let buf = "";
    for (const s of subs) {
      if (buf && buf.length + s.length > MAX_CUE_CHARS) {
        pieces.push(buf);
        buf = s;
      } else {
        buf += s;
      }
    }
    if (buf) pieces.push(buf);
  }
  const merged: string[] = [];
  for (const p of pieces) {
    if (
      merged.length &&
      merged[merged.length - 1].length + p.length <= MAX_CUE_CHARS &&
      p.length < 12
    ) {
      merged[merged.length - 1] += p;
    } else {
      merged.push(p);
    }
  }
  return merged;
};

const ScrollingText: React.FC<{
  text: string;
  color: string;
  startSec: number;
  endSec: number;
}> = ({ text, color, startSec, endSec }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const cues = splitCues(text);
  const totalChars = cues.reduce((s, c) => s + c.length, 0) || 1;
  const dur = Math.max(0.5, endSec - startSec);
  const t = frame / fps - startSec; // 章内本地秒

  // 定位当前条 + 条内本地时间 + 本条时长
  let acc = 0;
  let activeIdx = 0;
  let localT = 0;
  let activeSpan = dur;
  for (let i = 0; i < cues.length; i++) {
    const span = (dur * cues[i].length) / totalChars;
    if (t < acc + span || i === cues.length - 1) {
      activeIdx = i;
      localT = Math.max(0, t - acc);
      activeSpan = span;
      break;
    }
    acc += span;
  }

  const fadeIn = interpolate(localT, [0, 0.22], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
  });
  const fadeOut = interpolate(localT, [Math.max(0, activeSpan - 0.22), Math.max(0.3, activeSpan)], [1, 0.55], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const y = spring({ frame, fps: 30, config: { damping: 15 }, from: 20, to: 0 });

  return (
    <div
      style={{
        position: "absolute",
        bottom: 80,
        left: 120,
        right: 120,
        textAlign: "center",
        fontFamily: "Microsoft YaHei",
        fontSize: 42,
        fontWeight: 600,
        color: "#fff",
        textShadow: "0 2px 8px rgba(0,0,0,0.6)",
        opacity: fadeIn * fadeOut,
        transform: `translateY(${y}px)`,
        lineHeight: 1.5,
      }}
      key={activeIdx}
    >
      {cues[activeIdx] ?? ""}
    </div>
  );
};

/* ─── 波形指示器 ─── */
const WaveformBar: React.FC<{
  active: boolean;
  delay: number;
  color: string;
}> = ({ active, delay, color }) => {
  const frame = useCurrentFrame();
  const t = (frame + delay) % 30;
  const height = active
    ? interpolate(Math.sin((t / 30) * Math.PI * 2), [-1, 1], [14, 64])
    : 10;

  return (
    <div
      style={{
        width: 6,
        height,
        borderRadius: 3,
        background: active ? color : "rgba(255,255,255,0.1)",
      }}
    />
  );
};

const Waveform: React.FC<{
  active: boolean;
  color: string;
}> = ({ active, color }) => (
  <div
    style={{
      display: "flex",
      gap: 4,
      alignItems: "flex-end",
      height: 70,
    }}
  >
    {Array.from({ length: 28 }).map((_, i) => (
      <WaveformBar key={i} active={active} delay={i * 1.5} color={color} />
    ))}
  </div>
);

/* ─── 进度条 ─── */
const ProgressBar: React.FC<{
  progress: number; // 0..1 全局播放进度,按帧计算(Remotion 里 CSS transition 不可确定,禁用)
  color: string;
}> = ({ progress, color }) => (
  <div
    style={{
      position: "absolute",
      bottom: 0,
      left: 0,
      right: 0,
      height: 4,
      background: "rgba(255,255,255,0.08)",
    }}
  >
    <div
      style={{
        width: `${Math.min(100, Math.max(0, progress * 100))}%`,
        height: "100%",
        background: `linear-gradient(90deg, ${color}, ${color}88)`,
      }}
    />
  </div>
);

/* ─── 主组件 ─── */
export const Podcast: React.FC<PodcastProps> = ({
  title,
  chapters,
  renderWindow,
}) => {
  const { fps } = useVideoConfig();
  const frame = useCurrentFrame();
  const speakerColors: Record<string, string> = {
    A: "#3b5bfd",
    B: "#e8506e",
  };

  if (chapters.length === 0) {
    return (
      <AbsoluteFill style={{ background: "#121622" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            height: "100%",
            color: "#fff",
            fontSize: 48,
            fontFamily: "Microsoft YaHei",
          }}
        >
          No chapters
        </div>
      </AbsoluteFill>
    );
  }

  const currentChapter =
    chapters.find((ch) => {
      const startFrame = Math.floor(ch.start * fps);
      const endFrame = Math.floor(ch.end * fps);
      return frame >= startFrame && frame < endFrame;
    }) ?? chapters[chapters.length - 1];

  return (
    <AbsoluteFill style={{ background: "#121622" }}>
      <AnimatedBackground hue={220} />

      {/* 顶部标题 */}
      <div
        style={{
          position: "absolute",
          top: 40,
          left: 0,
          right: 0,
          textAlign: "center",
          fontFamily: "Microsoft YaHei",
          fontSize: 24,
          fontWeight: 700,
          color: "rgba(255,255,255,0.4)",
          letterSpacing: 2,
        }}
      >
        {title}
      </div>

      {/* 中间:说话人区 */}
      <div
        style={{
          position: "absolute",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          display: "flex",
          gap: 60,
          alignItems: "center",
        }}
      >
        {Object.entries(speakerColors).map(([spk, color]) => {
          const speakerData = chapters.find((c) => c.speaker === spk);
          const speakerName = speakerData?.speakerName || spk;
          const avatarFile = speakerData?.avatarFile;
          const isActive = currentChapter?.speaker === spk;
          return (
            <div
              key={spk}
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: 20,
              }}
            >
              <SpeakerAvatar
                name={speakerName}
                active={isActive}
                color={color}
                avatarFile={avatarFile}
              />
              <div
                style={{
                  fontFamily: "Microsoft YaHei",
                  fontSize: 24,
                  fontWeight: 600,
                  color: isActive ? "#fff" : "rgba(255,255,255,0.3)",
                }}
              >
                {speakerName}
              </div>
              <Waveform active={isActive} color={color} />
            </div>
          );
        })}
      </div>

      {/* 当前说话人名字(大字) */}
      <div
        style={{
          position: "absolute",
          top: 120,
          left: 0,
          right: 0,
          textAlign: "center",
          fontFamily: "Microsoft YaHei",
          fontSize: 56,
          fontWeight: 800,
          color: speakerColors[currentChapter?.speaker ?? "A"],
          textShadow: `0 0 40px ${speakerColors[currentChapter?.speaker ?? "A"]}44`,
        }}
      >
        {currentChapter?.speakerName}
      </div>

      {/* 字幕 */}
      {currentChapter && (
        <ScrollingText
          text={currentChapter.text}
          color={speakerColors[currentChapter.speaker]}
          startSec={currentChapter.start}
          endSec={currentChapter.end}
        />
      )}

      {/* 章节编号 */}
      <div
        style={{
          position: "absolute",
          bottom: 50,
          right: 60,
          fontFamily: "Microsoft YaHei",
          fontSize: 18,
          color: "rgba(255,255,255,0.3)",
        }}
      >
        {chapters.indexOf(currentChapter) + 1} / {chapters.length}
      </div>

      {/* 水印 */}
      <div
        style={{
          position: "absolute",
          bottom: 50,
          left: 40,
          fontFamily: "Microsoft YaHei",
          fontSize: 28,
          color: "rgba(255,255,255,0.15)",
        }}
      >
        wzx
      </div>

      <ProgressBar
        progress={frame / (chapters[chapters.length - 1].end * fps)}
        color={speakerColors[currentChapter?.speaker ?? "A"]}
      />

      {/* 逐段音频序列(分块渲染时只挂载窗口附近的章,防全量挂载超时) */}
      {chapters
        .filter((ch) => {
          if (!renderWindow) return true;
          const margin = 100 * 30; // 前后各留 100s 余量
          return (
            ch.end * 30 > renderWindow.from - margin &&
            ch.start * 30 < renderWindow.to + margin
          );
        })
        .map((ch) => {
          const from = Math.floor(ch.start * 30);
          const durationInFrames = Math.ceil((ch.end - ch.start) * 30);
          return (
            <Sequence
              key={ch.id}
              from={from}
              durationInFrames={durationInFrames}
            >
              <Audio src={staticFile(ch.audioFile)} />
            </Sequence>
          );
        })}
    </AbsoluteFill>
  );
};
