' AgentProxyHub resident scheduler daemon silent launcher.
' ASCII-ONLY ON PURPOSE.
Option Explicit

Dim fso, sh, wmi, procs, dir, schedScript, q, proc, isRunning

q = Chr(34)
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
schedScript = dir & "\core\resident_scheduler.py"
If Not fso.FileExists(schedScript) Then
    schedScript = dir & "\..\core\resident_scheduler.py"
End If
If Not fso.FileExists(schedScript) Then WScript.Quit 2

Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Set procs = wmi.ExecQuery("SELECT ProcessId, CommandLine FROM Win32_Process WHERE Name='python.exe' OR Name='pythonw.exe'")
isRunning = False
On Error Resume Next
For Each proc In procs
    If Not IsNull(proc.CommandLine) Then
        If InStr(1, proc.CommandLine, "resident_scheduler.py", 1) > 0 Then
            isRunning = True
            Exit For
        End If
    End If
Next
On Error GoTo 0

If Not isRunning Then
    Set sh = CreateObject("WScript.Shell")
    sh.CurrentDirectory = fso.GetParentFolderName(schedScript) & "\.."
    sh.Run "pythonw.exe " & q & schedScript & q & " --daemon", 0, False
End If

WScript.Quit 0
