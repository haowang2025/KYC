"""
Compatibility entrypoint.

- API app: `uvicorn server:app`
- CLI: `python server.py ...`

Core code lives in the `clearcheck` package.
"""

from clearcheck.api import app  # re-export for uvicorn
from clearcheck.cli import main

if __name__ == "__main__":
    main()

