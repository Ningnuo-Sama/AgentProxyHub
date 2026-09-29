' AgentProxyHub panel launcher - zero console window.
' Runs ui\panel.ps1 via powershell with hidden window style.
Option Explicit
Dim sh, dir
Set sh = CreateObject("WScript.Shell")
dir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir
sh.Run Chr(34) & "powershell.exe" & Chr(34) & " -NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File " & Chr(34) & dir & "\ui\panel.ps1" & Chr(34), 0, False