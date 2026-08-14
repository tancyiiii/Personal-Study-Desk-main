Option Explicit
Dim fso, shell, base
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
base = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = base
shell.Run """" & base & "\.venv\Scripts\pythonw.exe"" """" & base & "\main_gui.py""", 0, False
