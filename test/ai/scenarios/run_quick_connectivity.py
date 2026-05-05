"""Quick AI connectivity test - all output goes to tmp/ai_test_out.txt"""
import asyncio
import logging
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUT = ROOT / 'tmp' / 'ai_test_out.txt'
OUT.parent.mkdir(parents=True, exist_ok=True)

# Pre-import before asyncio.run() to avoid deadlock with threaded imports in
# core.ai.__init__.
import core.ai  # noqa: F401

class Logger:
    def __init__(self, path):
        self.f = open(path, 'w', encoding='utf-8', buffering=1)  # line-buffered
        self._orig = sys.stdout
    def write(self, s):
        self.f.write(s)
        self._orig.write(s)
        self.f.flush()
    def flush(self):
        self.f.flush()
        self._orig.flush()

sys.stdout = Logger(OUT)
sys.stderr = sys.stdout

try:
    logging.basicConfig(level=logging.INFO)
    print(f'[{time.strftime("%H:%M:%S")}] START')
    
    # Load env
    from dotenv import load_dotenv
    env = Path(ROOT) / '.env'
    if env.exists():
        load_dotenv(dotenv_path=env, override=False, encoding='utf-8-sig')
    print(f'[{time.strftime("%H:%M:%S")}] .env loaded')

    # Patch ConcurrentPool
    print(f'[{time.strftime("%H:%M:%S")}] Importing _shared...')
    from core.ai.shared import ConcurrentPool
    ConcurrentPool.can_accept = lambda self, key: True
    ConcurrentPool.acquire = lambda self, key: 1
    ConcurrentPool.release = lambda self, key: 0
    ConcurrentPool.get_count = lambda self, key: 0
    print(f'[{time.strftime("%H:%M:%S")}] ConcurrentPool patched')

    # Build CS
    print(f'[{time.strftime("%H:%M:%S")}] Importing CompletionService...')
    from core.ai import CompletionClient, CompletionService
    print(f'[{time.strftime("%H:%M:%S")}] Building CS...')
    
    tts = os.environ.get('TTS_APIKEY')
    orr = os.environ.get('OPENROUTER_API_KEY')
    print(f'  TTS key: {"yes" if tts else "no"}, OR key: {"yes" if orr else "no"}')
    
    clients = []
    if tts:
        c = CompletionClient.CreateThinkThinkSynClient(**CompletionService.ThinkThinkSynDefaultClientParams.OMNI)
        clients.append(c)
        print(f'  TTS client OK')
    if orr:
        c = CompletionClient.CreateOpenRouterClient()
        clients.append(c)
        print(f'  OR client OK')
    
    cs = CompletionService(*clients)
    print(f'[{time.strftime("%H:%M:%S")}] CS ready ({len(clients)} clients)')

    # Simple AI call
    print(f'[{time.strftime("%H:%M:%S")}] Calling AI...')
    async def call():
        return await cs.complete(messages=[{'role': 'user', 'content': 'Reply with exactly: TEST_OK_12345'}])
    
    t0 = time.time()
    result = asyncio.run(call())
    dt = time.time() - t0
    print(f'[{time.strftime("%H:%M:%S")}] Response ({dt:.1f}s): {repr(result[:300]) if result else "EMPTY"}')
    print('SUCCESS')

except BaseException as e:
    print(f'EXCEPTION: {type(e).__name__}: {e}')
    print(traceback.format_exc())
finally:
    print(f'[{time.strftime("%H:%M:%S")}] END')
