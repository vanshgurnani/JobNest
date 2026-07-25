from __future__ import annotations

import sys
from pathlib import Path

# Redirect execution to scrapers/scrape_jobs.py
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scrapers.scrape_jobs import main

if __name__ == "__main__":
    main()
