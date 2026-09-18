import sys
from pathlib import Path

BUILD_ROOT = Path(__file__).resolve().parent.parent
if str(BUILD_ROOT) not in sys.path:
    sys.path.insert(0, str(BUILD_ROOT))
