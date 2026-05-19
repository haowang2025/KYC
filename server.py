"""
Compatibility entrypoint.

- API app: `uvicorn server:app`
- CLI: `python server.py ...`

Core code lives in the `triage` package.
"""

from triage.api import app  # re-export for uvicorn
from triage.cli import main

if __name__ == "__main__":
    main()
