# Build a Windows distribution

The repository tracks the application sources and build recipe. `build/` and `dist/` are generated locally and excluded from Git. Distribute a ZIP of the completed application through GitHub Releases.

## Prepare a working build environment

From the repository root in PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\pyside6-rcc.exe CPS_resources_from_qt.qrc -o CPS_resources_from_qt.py
.\.venv\Scripts\python.exe Voice_Changer.py
```

The dependency lists in the starter are inferred from the supplied main Python file. They are not a substitute for the exact versions used in a verified build. Keep `requirements-lock.txt` from your tested, project-specific environment and use it for repeatable releases:

```powershell
.\.venv\Scripts\python.exe -m pip freeze > requirements-lock.txt
.\.venv\Scripts\python.exe --version
```

Record the Python version, PyInstaller version, and Windows version in the release notes or build documentation.

## Check the maintained recipe

The starter does not include or validate `CPSMDVoiceMOD.spec`; copy the real file from the project.

- Keep paths in the recipe relative to the project, rather than tied to your own computer.
- Include the `.ui` file, the `.qss` file, and resources opened directly through `app_resource_path` in the recipe's data files.
- The supplied code reads `darkngreen_palette.qss`, while the file listing shows `darkgreen_palette.qss`. Align the filename in the source and recipe before building.
- Resources imported through `CPS_resources_from_qt.py` are embedded in that module. Keep the `.qrc` and SVG files in Git so they can be edited and regenerated.

Build using the existing recipe, without replacing it with a plain command that omits its data-file configuration:

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm CPSMDVoiceMOD.spec
```

Build the Windows executable on Windows and verify the actual architecture before adding an architecture label to the release asset.

## Verify the build

Move a copy of the complete `dist/CPSMDVoiceMOD` folder outside the source tree. Launch the executable, check icons and styles, switch effects, mute/unmute, save and play a WAV recording, and close the application. Also verify it on another Windows computer or a clean Windows virtual machine without a Python development environment.

Before finalizing a release, verify that the source revision tagged for the release corresponds to the distributed executable.

## Licenses in the bundle

The project's MIT license applies to its original code and application assets. It does not replace licenses of Python, PySide6/Qt, PyAudio/PortAudio, NumPy, SciPy, Matplotlib, or any other component actually included in the bundle.

Prepare a `THIRD_PARTY_NOTICES.txt` and a `licenses/` folder using the exact components and versions you distribute. Preserve the required notices and full license texts. For LGPL PySide6/Qt components, also satisfy the applicable source-availability and library replacement/relinking requirements. MIT licensing of your own application does not remove those obligations. Check the actual Qt modules in the bundle because some modules are available under GPL rather than LGPL.

Official references:

- [Qt open-source obligations](https://www.qt.io/development/open-source-lgpl-obligations)
- [Qt for Python third-party licenses](https://doc.qt.io/qtforpython-6/licenses.html)
- [PyInstaller licensing exception](https://pyinstaller.org/en/stable/license.html)

These instructions do not certify the contents or license compliance of a binary bundle that has not been provided for inspection.

## Prepare the download

Keep the entire `CPSMDVoiceMOD` folder, including `CPSMDVoiceMOD.exe`, `_internal`, and all other produced files. Add the project's license and the completed third-party notices/license files before creating the ZIP. Upload that ZIP as a release asset; the automatically generated Source code archives will not contain the ignored `dist/` folder.
