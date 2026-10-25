"""Play only the fixed local farewell asset and wait for actual speaker drain."""
import asyncio,signal,sys,wave
from pathlib import Path
from player import Player,PlayerConfig
async def main():
 root=Path(__file__).resolve().parents[2]
 player=Player(PlayerConfig(root,sys.argv[1],sys.argv[2] if len(sys.argv)>2 else 'lx06-primary'))
 task=asyncio.current_task()
 asyncio.get_running_loop().add_signal_handler(signal.SIGTERM,task.cancel)
 try:
  with wave.open(str(root/'mac/realtime-voice/private/farewell.wav'),'rb') as f:
   if (f.getframerate(),f.getnchannels(),f.getsampwidth())!=(48000,2,2) or f.getnframes()>48000*5:raise ValueError('invalid fixed asset')
   data=f.readframes(f.getnframes())
  if not data:raise ValueError('empty fixed asset')
  await player.write(data)
  await player.drain()
 finally:await player.close()
if __name__=='__main__':asyncio.run(main())
