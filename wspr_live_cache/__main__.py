from __future__ import annotations

import uvicorn

uvicorn.run('wspr_live_cache.main:app', host='0.0.0.0', port=8081)
