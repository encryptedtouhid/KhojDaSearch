# Khoj Da Search

A cross-platform desktop search application inspired by macOS Spotlight that allows you to quickly find files on your system with a simple keyboard shortcut.

## Features

- **Global Search**: Press Alt+Space to instantly search your files from anywhere
- **Cross-Platform**: Works on Windows, macOS, and Linux
- **Spotlight-like Interface**: Clean, minimal UI that appears in the center of your screen
- **Adaptive Results**: Shows relevant files as you type
- **Persistent Indexing**: Maintains a database of your files for fast searching
- **Auto-hiding**: Disappears when you click outside or switch to another application

## Installation

### Requirements
- Python 3.6 or higher (tested with Python 3.10)
- PyQt5
- pynput

### Install Dependencies
```bash
pip install PyQt5 pynput
```

### Download and Run
1. Save the `khoj_da_search.py` file to your preferred location
2. Run it:
```bash
python khoj_da_search.py
```

## Usage

1. **First Launch**: On first run, the application will index your files (this may take a few minutes)
2. **Open Search**: Press Alt+Space to open the search bar
3. **Search Files**: Start typing to see matching results
4. **Navigate Results**: Use up/down arrow keys to navigate through results
5. **Open Files**: Press Enter to open the selected file, or double-click it
6. **Additional Options**: Right-click a result for more options:
   - Open file
   - Open containing folder
   - Copy file path
7. **Dismiss Search**: Click anywhere outside the search window, press Escape, or switch to another application

## Data Storage

The application stores its index database in a platform-specific location:
- **Windows**: `%APPDATA%\KhojDaSearch\search_index.db`
- **macOS**: `~/Library/Application Support/KhojDaSearch/search_index.db`
- **Linux**: `~/.local/share/KhojDaSearch/search_index.db`

This ensures the index persists between application restarts and is stored according to platform conventions.

## Auto-start on Boot (Optional)

### Windows
1. Create a shortcut to the script
2. Press Win+R and type `shell:startup`
3. Move the shortcut to the Startup folder

### macOS
1. Open System Preferences
2. Go to Users & Groups
3. Select your user account and click on "Login Items"
4. Click the "+" button and add the script

### Linux
Create a .desktop file in `~/.config/autostart/`:
```
[Desktop Entry]
Type=Application
Name=Khoj Da Search
Exec=python /path/to/khoj_da_search.py
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
```

## Troubleshooting

### Search Not Appearing
- Ensure no other application is using the Alt+Space hotkey
- Try restarting the application

### Slow Indexing
- The initial indexing might take time depending on the number of files
- Subsequent launches will be faster as the index is reused

### Missing Files in Search
- By default, hidden files and system directories are excluded
- The application indexes most common file locations

## Building a Standalone Executable (Optional)

You can create a standalone executable using PyInstaller:

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "Khoj Da Search" khoj_da_search.py
```

The executable will be created in the `dist` directory.