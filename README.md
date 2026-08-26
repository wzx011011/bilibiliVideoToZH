# Bilibili Video Translation Workspace

This repository combines two related production paths:

- `src/`, `episodes/`, `subtitles/`, and `tests/`: the Bilibili dubbing pipeline using OCR, Doubao narration, ASR alignment, and video packaging.
- `work/transformer-video-series/`: the Remotion-based Transformer explainer series, including semantic/terminology profiles, timing validation, and reproducible rendering scripts.

## Dubbing pipeline

```text
download -> OCR subtitles -> Doubao narration -> ASR alignment -> bilingual delivery
```

See the repository workflow and the source README for the end-to-end episode commands. Generated videos, source downloads, audio, logs, and model caches are intentionally excluded from Git.

## Transformer video series

Read [`work/transformer-video-series/README.md`](work/transformer-video-series/README.md) for setup and rendering:

```powershell
cd work/transformer-video-series
pnpm check
pnpm timing:validate
pnpm pipeline:terms
```

The renderer keeps narration, timing JSON, chapter structure, and profile configuration in source control so a clone can reproduce the composition after installing dependencies and supplying local audio.
