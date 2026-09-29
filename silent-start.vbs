' AgentProxyHub silent launcher.
' ASCII-ONLY ON PURPOSE: cscript reads .vbs in the ANSI codepage.
' Exit codes: 0 = launched, 1 = already running, 2 = mihomo.exe missing,
'             3 = config.yaml missing, 4 = silent-run.bat missing.
Option Explicit

Dim fso, sh, wmi, procs, dir, exe, cfg, runner, logDir, logFile, q

q = Chr(34)
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)

exe = dir & "\bin\mihomo.exe"
If Not fso.FileExists(exe) Then exe = dir & "\mihomo.exe"
If Not fso.FileExists(exe) Then WScript.Quit 2

cfg = dir & "\config\config.yaml"
If Not fso.FileExists(cfg) Then cfg = dir & "\config.yaml"
If Not fso.FileExists(cfg) Then WScript.Quit 3

runner = dir & "\silent-run.bat"
If Not fso.FileExists(runner) Then runner = dir & "\scripts\silent-run.bat"
If Not fso.FileExists(runner) Then WScript.Quit 4

Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Set procs = wmi.ExecQuery("SELECT ProcessId FROM Win32_Process WHERE Name='mihomo.exe'")
If procs.Count > 0 Then WScript.Quit 1

logDir = dir & "\logs"
If Not fso.FolderExists(logDir) Then fso.CreateFolder(logDir)
logFile = logDir & "\bridge.log"
If fso.FileExists(logFile) Then
    If fso.GetFile(logFile).Size > 5242880 Then fso.DeleteFile logFile, True
End If

Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = dir
sh.Run q & runner & q, 0, False

WScript.Quit 0