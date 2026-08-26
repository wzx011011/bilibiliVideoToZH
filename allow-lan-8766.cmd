@echo off
REM 以管理员身份运行本文件,放行 pipeline-admin 的 8766 端口入站(局域网访问)
netsh advfirewall firewall delete rule name="pipeline-admin-8766" >nul 2>&1
netsh advfirewall firewall add rule name="pipeline-admin-8766" dir=in action=allow protocol=TCP localport=8766
if errorlevel 1 (
  echo.
  echo [失败] 请右键本文件,选择"以管理员身份运行"
  pause
  exit /b 1
)
echo.
echo [OK] 8766 端口已放行,局域网设备现在可以访问 http://本机IP:8766
pause
