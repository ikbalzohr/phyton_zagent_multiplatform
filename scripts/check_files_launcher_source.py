"""Source assertions only; not PowerShell parser/runtime validation."""
from pathlib import Path
import unittest

class FilesLauncherSource(unittest.TestCase):
    def test_files_interpreter_is_explicit_and_restored(self):
        text = (Path(__file__).resolve().parents[1] / 'packaging/scripts/Start-OwnerCore.ps1').read_text()
        self.assertIn("'Zagent-Envs\\files\\Scripts\\python.exe'", text)
        self.assertIn('$previousFiles = $env:ZAGENT_FILES_PYTHON', text)
        self.assertIn('$env:ZAGENT_FILES_PYTHON = $filesPython', text)
        self.assertIn('$env:ZAGENT_FILES_PYTHON = $previousFiles', text)
        self.assertLess(text.index('Known isolated Files Python missing'), text.index('& $CoreExecutable'))
        self.assertNotIn('SetEnvironmentVariable', text)

if __name__ == '__main__':
    unittest.main()
