# Copyright (C) 2026 Open HamClock Backend (OHB) Contributors
# License: GNU Affero General Public License v3.0 (AGPLv3)
# See LICENSE file or <https://www.gnu.org/licenses/agpl-3.0.html>
#

from __future__ import annotations
import asyncio
import sys
from multiprocessing import Process
import uvicorn

from .db import init_schema
from .config import settings
from .collector import main as collector_main

# Initialize the database schema once before starting workers or collector
init_schema(settings.db_path)

# Start the collector in a background process. This isolates the background 
# polling from the API's request handling, avoiding GIL contention and 
# providing better resource isolation.
Process(target=collector_main, daemon=True).start()

uvicorn.run('wspr_live_cache.main:app', host='0.0.0.0', port=5001, workers=settings.workers)
