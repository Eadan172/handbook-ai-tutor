' AI Learning Tutor - silent launcher
' Double-click this file to start backend + frontend and open the browser
' with NO console window. It runs start.bat /silent in a hidden window.
Option Explicit

Dim fso, ws, scriptDir, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set ws = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
ws.CurrentDirectory = scriptDir

' 0 = hidden window, False = do not wait for the process to exit
cmd = Chr(34) & scriptDir & "\start.bat" & Chr(34) & " /silent"
ws.Run cmd, 0, False