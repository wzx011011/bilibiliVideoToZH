"""声纹标注纯逻辑:槽聚合窗口 + 低置信沿用/首窗 carry(无 torch 依赖,可单测)。

diarize_slots.py 的历史 bug:carry 里存的是整个窗口(list),写回时
`list(carry) + w` 得到嵌套列表,`slot["speaker"]` 直接 TypeError
(jensen-huang-nvidia 任务实测)。本模块把窗口构建与 carry 展开收敛为
纯函数并保证槽位字典展开。
"""
from __future__ import annotations

GAP = 2.0      # 槽间停顿超过此值切窗
WIN_TARGET = 6.0
WIN_MAX = 12.0
LOW_MARGIN = 0.04


def build_windows(slots: list[dict], gap: float = GAP,
                  win_max: float = WIN_MAX) -> list[list[dict]]:
    """相邻槽聚成窗口:gap 超限或窗口超长即切。"""
    windows: list[list[dict]] = []
    cur: list[dict] = []
    for s in slots:
        if cur and (s["start"] - cur[-1]["end"] > gap
                    or s["end"] - cur[0]["start"] > win_max):
            windows.append(cur)
            cur = []
        cur.append(s)
        if s["end"] - cur[0]["start"] > win_max:
            windows.append(cur)
            cur = []
    if cur:
        windows.append(cur)
    return windows


def label_windows(windows: list[list[dict]], classify,
                  low_margin: float = LOW_MARGIN,
                  evidence: str = "campplus-window",
                  default_speaker: str = "A") -> dict[str, float]:
    """逐窗定说话人并写回槽位字典,返回 {speaker: 累计秒数}。

    classify(window) -> (speaker, margin);margin < low_margin 时:
      有前窗 → 沿用前窗标签;无前窗 → 进 carry,等下一个高置信窗一起定。
    EOF 仍留 carry(整段开头就低置信)→ 用 default_speaker 兜底,不留悬空槽。
    """
    prev: str | None = None
    carry: list[list[dict]] = []
    stats: dict[str, float] = {}

    def write(w: list[dict], spk: str, ev: str) -> None:
        for slot in w:
            slot["speaker"] = spk
            slot["relabel_evidence"] = ev
        stats[spk] = stats.get(spk, 0.0) + (w[-1]["end"] - w[0]["start"])

    for w in windows:
        if not w:
            continue
        spk, margin = classify(w)
        if margin < low_margin:
            if prev is not None:
                spk = prev
            else:
                carry.append(w)
                continue
        prev = spk
        for cw in carry:
            write(cw, spk, evidence)
        carry = []
        write(w, spk, evidence)
    for cw in carry:
        write(cw, prev or default_speaker, evidence + "-eof")
    return stats
