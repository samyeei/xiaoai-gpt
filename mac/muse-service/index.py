"""Loopback Muse service entry point. Does not print config or credential values."""
import argparse
import asyncio
import contextlib
import json
import logging
import pathlib
import signal
from service import DEFAULT_STATE, MuseBackend, JobService, load_config
from muse_http import JobHTTP

async def serve(directory,port):
    # Upstream diagnostics can include errors supplied by an untrusted peer.
    logging.getLogger('musegadget').setLevel(logging.CRITICAL)
    backend=MuseBackend(directory);jobs=JobService(directory,backend);http=JobHTTP(jobs,port)
    stop=asyncio.Event();loop=asyncio.get_running_loop()
    for sig in (signal.SIGINT,signal.SIGTERM):loop.add_signal_handler(sig,stop.set)
    task=None
    try:
        await http.start();jobs.start();task=asyncio.create_task(backend.run())
        print(json.dumps({'service':'mac-muse','listening':True,'host':'127.0.0.1','port':port}),flush=True)
        await stop.wait()
    finally:
        await http.close();await jobs.close();backend.stop.set()
        if task:
            try:await asyncio.wait_for(task,5)
            except asyncio.TimeoutError:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):await task
        for sig in (signal.SIGINT,signal.SIGTERM):loop.remove_signal_handler(sig)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',nargs='?',choices=['run','init'],default='run');parser.add_argument('--state-dir',type=pathlib.Path,default=DEFAULT_STATE);parser.add_argument('--port',type=int,default=4414)
    args=parser.parse_args()
    try:
        if not 1<=args.port<=65535:raise ValueError()
        if args.command=='init':load_config(args.state_dir);print('{"service":"mac-muse","initialized":true}')
        else:asyncio.run(serve(args.state_dir,args.port))
        return 0
    except Exception:print('{"service":"mac-muse","error":"startup unavailable"}');return 1
if __name__=='__main__':raise SystemExit(main())
