Set shell = CreateObject("WScript.Shell")
scriptDir = Replace(WScript.ScriptFullName, WScript.ScriptName, "")
cmd = "cmd /c """ & scriptDir & "launch_app_prod_silent.bat"""
shell.Run cmd, 0, False
