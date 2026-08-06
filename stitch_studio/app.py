from __future__ import annotations

import os


os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from stitch_studio.ui_qt import main


if __name__ == "__main__":
    main()
