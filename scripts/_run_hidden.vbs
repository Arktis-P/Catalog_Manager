if WScript.Arguments.Count < 1 Then
  WScript.Echo "Usage: cscript //nologo _run_hidden.vbs ""command"""
  WScript.Quit 1
End If

CreateObject("WScript.Shell").Run WScript.Arguments(0), 0, False
