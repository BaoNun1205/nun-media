@echo off
cd /d "%~dp0"
set KMP_DUPLICATE_LIB_OK=TRUE
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
py -3.11 app.py
