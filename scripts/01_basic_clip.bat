@echo off
REM ============================================================
REM  Phase 1 - Easy Windows launcher for basic vertical clip
REM  Works on Windows 7
REM ============================================================

REM ---------- CONFIGURE THESE ----------
set INPUT=..\input\long_video.mp4
set OUTPUT=..\output\short_01.mp4
set START=00:01:00
set END=00:01:25

REM If ffmpeg is not in PATH, set the full path here:
REM set FFMPEG=C:\ffmpeg\bin\ffmpeg.exe
set FFMPEG=ffmpeg
REM -------------------------------------

echo.
echo ========================================
echo  Video-to-Shorts - Phase 1 Basic Clip
echo ========================================
echo Input : %INPUT%
echo Output: %OUTPUT%
echo Start : %START%
echo End   : %END%
echo.

REM Create output folder if it doesn't exist
if not exist "..\output" mkdir "..\output"

REM Simple center-crop to 9:16 + scale to 1080x1920
%FFMPEG% -y -ss %START% -to %END% -i "%INPUT%" -vf "crop=ih*9/16:ih,scale=1080:1920" -c:v libx264 -crf 20 -preset medium -c:a aac -b:a 128k -movflags +faststart "%OUTPUT%"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo SUCCESS! Short saved to: %OUTPUT%
) else (
    echo.
    echo ERROR: FFmpeg failed. Check the messages above.
)

echo.
pause