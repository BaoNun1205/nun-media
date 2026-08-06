@echo off
cd /d "%~dp0"
set KMP_DUPLICATE_LIB_OK=TRUE
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
if "%STITCH_API_PORT%"=="" set STITCH_API_PORT=8008
py -3.11 -m uvicorn backend.main:app --host 127.0.0.1 --port %STITCH_API_PORT% --reload
