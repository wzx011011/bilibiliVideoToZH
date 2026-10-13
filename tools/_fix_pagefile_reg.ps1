$ErrorActionPreference = 'Stop'
# 注册表方式写页面文件配置(比 CIM 创建可靠)
Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management' `
    -Name PagingFiles -Value 'C:\pagefile.sys 16384 16384' -Type MultiString
"D 盘旧文件清理提示:重启后 D:\pagefile.sys 可手动删除(若残留)"
(Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management').PagingFiles
Write-Host '写入完成,重启生效。' -ForegroundColor Green
Start-Sleep 8
