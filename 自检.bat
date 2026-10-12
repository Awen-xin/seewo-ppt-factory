@echo off
cd /d "%~dp0"
echo ============================================
echo   希沃课件工厂 - 环境自检
echo ============================================
echo.
set PY=python
where python >nul 2>nul
if %errorlevel%==0 goto found
set PY=py -3
where py >nul 2>nul
if %errorlevel%==0 goto found
echo [X] 没找到 Python 3.x。请先安装 Python，并勾选 Add to PATH。
goto end
:found
echo 使用的命令: %PY%
echo.
echo [1/2] 配置自检（期望 6 项 OK）
echo --------------------------------------------
%PY% scripts\seewo_config.py
echo.
echo [2/2] 脚本自检（期望 16 个库型 + 3 个 CLI 通过）
echo --------------------------------------------
%PY% scripts\_selftest.py
:end
echo.
echo 自检结束。把上面的输出截图发给 AI 即可。
pause
