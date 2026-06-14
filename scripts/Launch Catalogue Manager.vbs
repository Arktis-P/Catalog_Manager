Set shell = CreateObject("WScript.Shell")
scriptDir = Replace(WScript.ScriptFullName, WScript.ScriptName, "")
cmd = "cmd /c """ & scriptDir & "launch_desktop.bat"""
shell.Run cmd, 0, False
