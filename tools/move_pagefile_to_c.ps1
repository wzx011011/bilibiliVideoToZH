# move_pagefile_to_c.ps1 —— 页面文件迁 C 盘(需管理员,跑完重启生效)
# 用法:右键"以管理员身份运行" PowerShell,执行本脚本,然后重启。
# 目的:把换页流量从机械盘挪到 NVMe,根治 HDD 满载/整机卡死。

$ErrorActionPreference = 'Stop'

$cs = Get-CimInstance Win32_ComputerSystem
if ($cs.AutomaticManagedPagefile) {
    Set-CimInstance -InputObject $cs -Property @{ AutomaticManagedPagefile = $false }
    "已关闭'自动管理虚拟内存'"
}

Get-CimInstance Win32_PageFileSetting |
    Where-Object { $_.Name -like 'D:*' } |
    ForEach-Object { Remove-CimInstance -InputObject $_; "已移除 D 盘页面文件: $($_.Name)" }

if (-not (Get-CimInstance Win32_PageFileSetting | Where-Object { $_.Name -like 'C:*' })) {
    New-CimInstance -ClassName Win32_PageFileSetting -Property @{
        Name = 'C:\pagefile.sys'; InitialSize = 16384; MaximumSize = 16384 } | Out-Null
    "已在 C 盘创建 16GB 固定页面文件"
}

""
"当前生效配置(重启后):"
Get-CimInstance Win32_PageFileSetting | Select-Object Name, InitialSize, MaximumSize | Format-Table -AutoSize
"请重启电脑完成迁移。"
