Option Explicit
Dim fso, shell, root, scriptPath, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
scriptPath = root & "\launcher\TooruDragonLauncher.ps1"
cmd = "powershell.exe -NoLogo -NoProfile -STA -ExecutionPolicy Bypass -File """ & scriptPath & """"
shell.Run cmd, 0, False
