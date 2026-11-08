import sys, time
sys.path.insert(0, 'CosyVoice')
sys.path.insert(0, 'CosyVoice/third_party/Matcha-TTS')
sys.path.insert(0, 'CosyVoice/third_party/Matcha-TTS/matcha')
t0 = time.time()
from cosyvoice.cli.cosyvoice import CosyVoice3
print('import ok', flush=True)
m = CosyVoice3(model_dir='/home/comfy/models/Fun-CosyVoice3-0.5B-2512',
               load_trt=False, load_vllm=False, fp16=False)
print('MODEL LOADED ok', round(time.time()-t0, 1), 's', flush=True)
