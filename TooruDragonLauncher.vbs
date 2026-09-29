Option Explicit
Dim fso, shell, root, scriptPath, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
scriptPath = root & "\launcher\TooruDragonLauncher.ps1"
cmd = "powershell.exe -NoLogo -NoProfile -STA -ExecutionPolicy Bypass -File """ & scriptPath & """"
If WScript.Arguments.Count > 0 Then
    If LCase(WScript.Arguments(0)) = "autostart" Then cmd = cmd & " -AutoStart"
End If
shell.Run cmd, 0, False
