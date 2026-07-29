from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from record_loopback import pcm16


def test_pcm16_clips_and_preserves_frame_shape():
    samples = np.array([[-1.5, -1.0], [0.0, 0.5], [1.0, 1.5]], dtype=np.float32)

    result = pcm16(samples)

    assert result.dtype == np.dtype("<i2")
    assert result.tolist() == [[-32767, -32767], [0, 16384], [32767, 32767]]


def test_pcm16_requires_frames_by_channels_shape():
    with pytest.raises(ValueError, match="frames, channels"):
        pcm16(np.array([0.0, 1.0]))
