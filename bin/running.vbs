' Hidden launcher for the running app - used by the desktop shortcut.
' Starts the server with no console window, then opens the browser.
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
sh.Run """" & root & "\bin\running.cmd"" noopen", 0, True
WScript.Sleep 1500
sh.Run "http://127.0.0.1:5001", 1, False
