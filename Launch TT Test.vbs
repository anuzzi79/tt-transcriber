Option Explicit
Dim shell, fs, root, command
Set shell = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
shell.Environment("Process")("TT_DATA_DIR") = root & "\.test-data"
shell.Environment("Process")("TT_TRANSCRIPT_DIR") = root & "\.test-transcripts"
shell.Environment("Process")("TT_DIAGNOSTICS") = "1"
shell.Environment("Process")("TT_SPEECH_MODEL") = "universal-3-6-pro"
command = "pythonw.exe " & Chr(34) & root & "\main.py" & Chr(34)
shell.Run command, 1, False
