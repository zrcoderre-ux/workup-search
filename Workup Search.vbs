' Workup Search.vbs - silent launcher
' Runs the sibling Workup Search.bat with no visible console window.
' Self-locating: launches the .bat next to this script, wherever the clone lives.
Dim fso, here, q
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
q = Chr(34)
CreateObject("WScript.Shell").Run q & here & "\Workup Search.bat" & q, 0, False
