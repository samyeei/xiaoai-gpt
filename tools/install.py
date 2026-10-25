#!/usr/bin/env python3
"""Public entry point; package imports are local to this checkout."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.installer.cli import main
if __name__=='__main__':raise SystemExit(main())
