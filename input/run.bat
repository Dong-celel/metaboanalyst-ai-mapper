@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

echo =============================================
echo MetaboAnalyst NameMap View Processor
echo =============================================
echo.
echo Input folder : %CD%\input
echo Output folder: %CD%\output
echo.

set "MAX_ITEMS="
set /p "MAX_ITEMS=Items to process (press Enter for ALL, or enter a test batch size): "

echo.
echo First enter the optional research goals and the 0-100 preference strength.
echo Then enter the DeepSeek API key at the hidden prompt.
echo Pasted characters will not be displayed. Press Enter after pasting.
echo.
if defined MAX_ITEMS goto run_limited
python main.py run --no-preflight --no-review --close-browser --browser-network direct --ask-research-goal --ask-deepseek-key
set "RUN_RESULT=%ERRORLEVEL%"
goto show_result

:run_limited
python main.py run --no-preflight --no-review --close-browser --max-items "%MAX_ITEMS%" --browser-network direct --ask-research-goal --ask-deepseek-key
set "RUN_RESULT=%ERRORLEVEL%"

:show_result

echo.
if not "%RUN_RESULT%"=="0" goto run_failed
echo Processing completed successfully.
echo Open the output folder to get the processed file.
goto run_finished

:run_failed
echo Processing did not complete. Review the error message above.

:run_finished
pause
exit /b %RUN_RESULT%
