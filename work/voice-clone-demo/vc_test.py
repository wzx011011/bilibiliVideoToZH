import sys
from pathlib import Path
import torch, torchaudio
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'CosyVoice')); sys.path.insert(0,str(ROOT/'CosyVoice'/'third_party'/'Matcha-TTS'))
PILOT=ROOT/'interview-pilot'

def main():
    if torch.cuda.is_available():
        torch.backends.cuda.matmul.allow_tf32=False; torch.backends.cudnn.allow_tf32=False
    from cosyvoice.cli.cosyvoice import AutoModel
    model=AutoModel(model_dir=str(ROOT/'models'/'CosyVoice2-0.5B'),load_jit=False,load_trt=False,load_vllm=False,fp16=False)
    source=str(PILOT/'parts'/'A1-mandarin-base.wav')
    for name in ('A','B'):
        ref=str(PILOT/cfg[name]['ref_wav'])
        pieces=[r['tts_speech'] for r in model.inference_vc(source,ref,stream=False)]
        out=PILOT/'parts'/f'A1-vc-{name}.wav'
        torchaudio.save(str(out),torch.cat(pieces,dim=1),model.sample_rate)
        print(name,out)

if __name__=='__main__':
    import json
    cfg=json.loads((PILOT/'pilot.json').read_text(encoding='utf-8'))
    main()
