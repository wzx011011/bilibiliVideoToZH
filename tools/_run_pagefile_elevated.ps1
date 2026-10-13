Start-Process powershell -Verb RunAs -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass',
    '-Command', "& 'E:\ai\bilibiliVideoToZH\tools\move_pagefile_to_c.ps1'; Write-Host ''; Write-Host '完成,可关闭本窗口' -ForegroundColor Green; Start-Sleep 8"
)
