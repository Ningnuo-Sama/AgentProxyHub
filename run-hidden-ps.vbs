' AgentProxyHub silent launcher for scheduled tasks (run-hidden-ps.vbs)
' ASCII-ONLY ON PURPOSE: cscript/wscript reads .vbs in the ANSI codepage.
'
' Usage: wscript.exe run-hidden-ps.vbs powershell.exe "D:\path\script.ps1"
'        wscript.exe run-hidden-ps.vbs pwsh.exe       "D:\path\script.ps1"
Option Explicit

Dim sh, q, eng, scr, cmd
q = Chr(34)

If WScript.Arguments.Count < 2 Then WScript.Quit 2

eng = WScript.Arguments(0)
scr = WScript.Arguments(1)

Set sh = CreateObject("WScript.Shell")
cmd = q & eng & q & " -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File " & q & scr & q
sh.Run cmd, 0, False

WScript.Quit 0
