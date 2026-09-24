' يشغل الحارس بدون نافذة سوداء
Set WShell = CreateObject("WScript.Shell")
WShell.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WShell.Run "pythonw watchdog.py", 0, False