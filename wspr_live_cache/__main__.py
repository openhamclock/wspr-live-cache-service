from __future__ import annotations
import asyncio
import sys

if len(sys.argv) > 1 and sys.argv[1] == 'collector':
    from .collector import run_collector
    asyncio.run(run_collector())
else:
    import uvicorn
    from .config import settings
    uvicorn.run('wspr_live_cache.main:app', host='0.0.0.0', port=5001, workers=settings.workers)
