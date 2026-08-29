@echo off
REM Build the single-file ForzaDesigner6.exe with PyInstaller.
REM Run from the ForzaDesigner6 directory after `py -m pip install -r requirements.txt`.

setlocal
cd /d "%~dp0"

REM Remove the old legacy executable name so there is only one expected app name.
if exist "dist\FD6MultiSupport.exe" del /q "dist\FD6MultiSupport.exe"

py -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name "ForzaDesigner6" ^
    --icon "tools\fd6.ico" ^
    --add-data "fd6\settings\profiles;fd6\settings\profiles" ^
    --add-data "fd6\inject\patterns;fd6\inject\patterns" ^
    --add-data "SplashScreen.mp4;." ^
    --add-data "Song1OpenSource.mp3;." ^
    --add-data "Song2OpenSource.mp3;." ^
    --add-data "Song3OpenSource.mp3;." ^
    --add-data "tools\fd6_128.png;tools" ^
    --add-data "AppIconTransparent.png;." ^
    --add-data "BlossomParticle.png;." ^
    --add-data "fonts;fonts" ^
    --add-data "Pink.png;." ^
    --add-data "Yellow.png;." ^
    --add-data "Purple.png;." ^
    --add-data "Green.png;." ^
    --add-data "Blue.png;." ^
    --add-data "Orange.png;." ^
    --hidden-import fd6.gui.music ^
    --hidden-import fd6.gui.particles ^
    --hidden-import fd6.gui.fonts ^
    --hidden-import fd6.gui.image_search ^
    --hidden-import PySide6.QtWebEngineCore ^
    --hidden-import PySide6.QtWebEngineWidgets ^
    --hidden-import PySide6.QtWebChannel ^
    --hidden-import PySide6.QtWebEngineQuick ^
    --hidden-import PySide6.QtPrintSupport ^
    --collect-submodules PySide6.QtWebEngineCore ^
    --collect-data PySide6 ^
    --collect-binaries PySide6 ^
    --hidden-import fd6.inject.cli ^
    --hidden-import fd6.inject.discovery ^
    --hidden-import fd6.inject.patterns_io ^
    --hidden-import fd6.inject.win_process ^
    --hidden-import fd6.inject.fh6_injector ^
    --hidden-import fd6.inject.game_profiles ^
    --hidden-import fd6.inject.rtti_locator ^
    --hidden-import fd6.suite ^
    --hidden-import fd6.ac ^
    --hidden-import fd6.ac.profiles ^
    --hidden-import fd6.ac.livery_paths ^
    --hidden-import fd6.ac.car_catalog ^
    --hidden-import fd6.ac.texture_pipeline ^
    --hidden-import fd6.ac.slot_planner ^
    --hidden-import fd6.ac.livery_writer ^
    --hidden-import fd6.gui.game_suite_dialog ^
    --hidden-import fd6.gui.ac_settings_panel ^
    --hidden-import fd6.gui.texture_preview_panel ^
    --hidden-import fd6.gui.inject_worker ^
    --hidden-import fd6.gui.inject_dialog ^
    --hidden-import fd6.gui.splash ^
    --hidden-import fd6.gui.brand_banner ^
    --hidden-import fd6.gui.themes ^
    --hidden-import fd6.shapegen.render ^
    --hidden-import fd6.shapegen.gpu ^
    --hidden-import PySide6.QtMultimedia ^
    --hidden-import PySide6.QtMultimediaWidgets ^
    -p . ^
    fd6\__main__.py

if errorlevel 1 (
    echo.
    echo BUILD FAILED - ForzaDesigner6.exe was NOT created.
    endlocal
    exit /b 1
)

if not exist "dist\ForzaDesigner6.exe" (
    echo.
    echo BUILD FAILED - PyInstaller finished but dist\ForzaDesigner6.exe was not found.
    endlocal
    exit /b 1
)

echo.
echo BUILD SUCCESSFUL: dist\ForzaDesigner6.exe
endlocal
