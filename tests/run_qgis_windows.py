"""Run the dependency-free QGIS C# contracts in Files' reduced environment.

The executable is explicit; this does not enroll or change executable policy.
"""
import os
import subprocess
import sys

def main():
    dotnet = sys.argv[1]
    env = os.environ.copy()
    # NuGet requires these Windows known-folder variables. Files deliberately
    # launches tools with a reduced environment; no private config is loaded.
    import ctypes
    from ctypes import wintypes
    def folder(csidl):
        buf=ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None,csidl,None,0,buf):
            raise RuntimeError('Windows known folder unavailable')
        return buf.value
    for key,csidl in {'APPDATA':26,'LOCALAPPDATA':28,'ProgramFiles':38,'ProgramData':35,'USERPROFILE':40}.items():
        env[key]=folder(csidl)
    result=subprocess.run([dotnet,*sys.argv[2:]],env=env)
    return result.returncode

if __name__=='__main__':raise SystemExit(main())
