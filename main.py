#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Khoj Da Search - A cross-platform Spotlight-like search utility
Compatible with Python 3.6+ (including Python 3.10)
"""

import os
import sys
import sqlite3
import time
from pathlib import Path
from datetime import datetime

# For the UI
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QLineEdit, QListWidget, QListWidgetItem, QLabel,
                             QMenu, QAction, QSystemTrayIcon, QDialog, QProgressBar)
from PyQt5.QtCore import Qt, QSize, pyqtSignal, QThread, QEvent
from PyQt5.QtGui import QIcon, QFont, QCursor

# For global hotkey
from pynput import keyboard


# Database path - use platform-specific application data directory
def get_app_data_path():
    """Get platform-specific path for application data"""
    app_name = "KhojDaSearch"

    if sys.platform == "win32":
        # Windows: Use %APPDATA%
        app_data = os.environ.get("APPDATA")
        if not app_data:
            app_data = os.path.expanduser("~")
        base_path = os.path.join(app_data, app_name)
    elif sys.platform == "darwin":
        # macOS: Use ~/Library/Application Support/
        base_path = os.path.expanduser(f"~/Library/Application Support/{app_name}")
    else:
        # Linux/Unix: Use ~/.local/share/
        base_path = os.path.expanduser(f"~/.local/share/{app_name}")

    # Create directory if it doesn't exist
    if not os.path.exists(base_path):
        os.makedirs(base_path)

    return base_path


# Path to the database file
DB_PATH = os.path.join(get_app_data_path(), "search_index.db")


class FileIndexer(QThread):
    """Thread to index files and directories"""
    progress_signal = pyqtSignal(str, int)  # Message and percentage
    finished_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.stopped = False
        self.total_files_estimated = 0
        self.files_processed = 0

    def run(self):
        """Index all files and directories"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Create table if it doesn't exist
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY,
            name TEXT,
            path TEXT,
            type TEXT,
            size INTEGER,
            modified_date TEXT,
            UNIQUE(path)
        )
        ''')
        conn.commit()

        # Start indexing
        drives = self._get_drives()

        # First, estimate the total number of files to index
        self.progress_signal.emit("Estimating total files...", 0)
        self._estimate_total_files(drives)

        # Now do the actual indexing
        self.files_processed = 0

        for drive in drives:
            if self.stopped:
                break

            percentage = self._get_percentage()
            self.progress_signal.emit(f"Indexing {drive}...", percentage)

            try:
                for root, dirs, files in os.walk(drive):
                    if self.stopped:
                        break

                    # Skip hidden directories
                    dirs_filtered = [d for d in dirs if not d.startswith('.') and not d.startswith('$')]
                    dirs[:] = dirs_filtered

                    for file in files:
                        if self.stopped:
                            break

                        # Skip hidden files
                        if file.startswith('.'):
                            continue

                        full_path = os.path.join(root, file)
                        try:
                            file_stat = os.stat(full_path)
                            file_type = os.path.splitext(file)[1].lower()
                            file_size = file_stat.st_size
                            modified_date = datetime.fromtimestamp(file_stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')

                            # Insert or replace in database
                            cursor.execute('''
                            INSERT OR REPLACE INTO files (name, path, type, size, modified_date) 
                            VALUES (?, ?, ?, ?, ?)
                            ''', (file, full_path, file_type, file_size, modified_date))

                            self.files_processed += 1

                            if self.files_processed % 500 == 0:
                                conn.commit()
                                percentage = self._get_percentage()
                                self.progress_signal.emit(
                                    f"Indexed {self.files_processed} files ({percentage}% complete)...",
                                    percentage
                                )

                        except (PermissionError, OSError):
                            continue
            except (PermissionError, OSError):
                continue

        conn.commit()
        conn.close()
        self.progress_signal.emit(f"Completed indexing {self.files_processed} files.", 100)
        self.finished_signal.emit()

    def stop(self):
        """Stop the indexing process"""
        self.stopped = True

    def _get_drives(self):
        """Get all available drives/roots based on the OS"""
        if sys.platform == "win32":
            from ctypes import windll
            drives = []
            bitmask = windll.kernel32.GetLogicalDrives()
            for letter in range(65, 91):  # A-Z
                if bitmask & 1:
                    drives.append(chr(letter) + ":\\")
                bitmask >>= 1
            return drives
        elif sys.platform == "darwin" or sys.platform.startswith("linux"):
            return ["/"]
        else:
            return [os.path.expanduser("~")]

    def _estimate_total_files(self, drives):
        """Estimate total number of files to index"""
        # This is a simplified estimation - we'll count files in a subset of directories
        sample_size = 0
        file_count = 0

        for drive in drives:
            try:
                for root, dirs, files in os.walk(drive):
                    # Skip hidden directories
                    dirs_filtered = [d for d in dirs if not d.startswith('.') and not d.startswith('$')]
                    dirs[:] = dirs_filtered

                    # Count files in this directory
                    file_count += len([f for f in files if not f.startswith('.')])

                    # Update sample size
                    sample_size += 1

                    # Only sample a subset of directories to speed up the estimation
                    if sample_size >= 20:  # Reduced from 50 to speed up initialization
                        break

                if sample_size >= 20:
                    break
            except (PermissionError, OSError):
                continue

        # Extrapolate for a rough estimate
        if sample_size > 0:
            # This formula is very approximate - it assumes a uniform distribution of files
            avg_files_per_dir = file_count / max(1, sample_size)
            estimated_dirs = self._estimate_dir_count(drives)
            self.total_files_estimated = max(1000, int(avg_files_per_dir * estimated_dirs))
        else:
            # Fallback to a reasonable default
            self.total_files_estimated = 10000  # Default estimate

        self.progress_signal.emit(f"Estimated approx. {self.total_files_estimated} files to index", 0)

    def _estimate_dir_count(self, drives):
        """Estimate the total number of directories"""
        # Again, a simplified estimation
        dir_count = 0
        sample_size = 0

        for drive in drives:
            try:
                for root, dirs, _ in os.walk(drive):
                    # Skip hidden directories
                    dirs_filtered = [d for d in dirs if not d.startswith('.') and not d.startswith('$')]
                    dirs[:] = dirs_filtered

                    # Count non-hidden directories
                    dir_count += len(dirs_filtered)

                    # Update sample size
                    sample_size += 1

                    # Only sample a small number of directories
                    if sample_size >= 10:  # Reduced from 20 to speed up initialization
                        break

                if sample_size >= 10:
                    break
            except (PermissionError, OSError):
                continue

        # Extrapolate based on typical directory structure
        if sample_size > 0:
            avg_dirs = dir_count / max(1, sample_size)
            # Rough estimate of total directories
            total_estimated = max(100, int(avg_dirs * 50))  # Assume ~50x more directories in total system
        else:
            total_estimated = 1000  # Fallback estimate

        return total_estimated

    def _get_percentage(self):
        """Calculate the percentage of completion"""
        if self.total_files_estimated <= 0:
            return 0

        percentage = min(99, int((self.files_processed / self.total_files_estimated) * 100))
        return percentage


class IndexingDialog(QDialog):
    """Dialog to show indexing progress"""

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Khoj Da Search - Indexing")
        self.setFixedSize(500, 250)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # Main layout
        layout = QVBoxLayout(self)

        # Create a container widget with styling
        container = QWidget()
        container.setStyleSheet("""
            background-color: rgba(40, 40, 40, 0.8);
            border-radius: 15px;
            border: 1px solid rgba(255, 255, 255, 0.1);
        """)
        container_layout = QVBoxLayout(container)

        # Title label
        title_label = QLabel("Khoj Da Search")
        title_label.setStyleSheet("""
            font-size: 20px;
            font-weight: bold;
            color: white;
            padding: 10px;
        """)
        title_label.setAlignment(Qt.AlignCenter)

        # Status message
        self.status_label = QLabel("Preparing to index files...")
        self.status_label.setStyleSheet("""
            font-size: 14px;
            color: rgba(255, 255, 255, 0.8);
            padding: 5px;
        """)
        self.status_label.setAlignment(Qt.AlignCenter)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 5px;
                padding: 1px;
                text-align: center;
                height: 20px;
                margin: 10px 20px;
                background-color: rgba(30, 30, 30, 0.5);
                color: white;
            }
            QProgressBar::chunk {
                background-color: rgba(65, 135, 230, 0.8);
                border-radius: 5px;
            }
        """)

        # Info label
        info_label = QLabel(
            "This may take a few minutes depending on the number of files.\nThe index will be saved for future use.")
        info_label.setStyleSheet("""
            font-size: 12px;
            color: rgba(255, 255, 255, 0.6);
            padding: 10px;
        """)
        info_label.setAlignment(Qt.AlignCenter)

        # Add widgets to container layout
        container_layout.addWidget(title_label)
        container_layout.addWidget(self.status_label)
        container_layout.addWidget(self.progress_bar)
        container_layout.addWidget(info_label)

        # Add container to main layout
        layout.addWidget(container)

        # Center dialog on screen
        self.center_on_screen()

    def center_on_screen(self):
        """Center the dialog on the screen"""
        screen_geometry = QApplication.desktop().availableGeometry()
        x = (screen_geometry.width() - self.width()) // 2
        y = (screen_geometry.height() - self.height()) // 2
        self.move(x, y)

    def update_status(self, message, percentage):
        """Update status message and progress bar"""
        self.status_label.setText(message)
        self.progress_bar.setValue(percentage)


class SearchBar(QWidget):
    """Main search bar widget similar to Spotlight"""
    closed = pyqtSignal()

    def __init__(self):
        super().__init__()

        # Window properties
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        # Set size and position - fixed width like Spotlight
        screen_geometry = QApplication.desktop().availableGeometry()
        self.fixed_width = int(screen_geometry.width() * 0.4)  # 40% of screen width
        self.min_height = 60  # Just enough for search bar
        self.max_height = int(screen_geometry.height() * 0.7)  # Maximum 70% of screen height

        # Position in the middle of the screen
        x = (screen_geometry.width() - self.fixed_width) // 2
        y = (screen_geometry.height() - self.min_height) // 2  # Center vertically
        self.setGeometry(x, y, self.fixed_width, self.min_height)

        # Main layout
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(0)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        # Search container (for styling the search field)
        search_container = QWidget()
        search_container.setFixedWidth(self.fixed_width)
        search_container.setMinimumHeight(60)
        search_container.setStyleSheet("""
            background-color: rgba(40, 40, 40, 0.8);
            border-radius: 10px;
            border: 1px solid rgba(255, 255, 255, 0.1);
        """)
        search_layout = QHBoxLayout(search_container)

        # Search icon
        search_icon = QLabel()
        search_icon.setFixedSize(24, 24)
        search_icon.setStyleSheet("""
            background-color: transparent;
            color: rgba(255, 255, 255, 0.7);
            font-size: 18px;
        """)
        search_icon.setText("🔍")
        search_layout.addWidget(search_icon)

        # Search input
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search files and folders...")
        self.search_input.textChanged.connect(self.search)
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: transparent;
                border: none;
                color: white;
                font-size: 16px;
                padding: 5px;
            }
            QLineEdit::placeholder {
                color: rgba(255, 255, 255, 0.5);
            }
        """)
        search_layout.addWidget(self.search_input)

        # Results container with fixed width to match search bar
        self.results_container = QWidget()
        self.results_container.setFixedWidth(self.fixed_width)
        self.results_container.setStyleSheet("""
            background-color: rgba(40, 40, 40, 0.8);
            border-radius: 10px;
            margin-top: 0px;
            border: 1px solid rgba(255, 255, 255, 0.1);
        """)
        self.results_container.setVisible(False)  # Hidden by default

        # Layout for results container
        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setContentsMargins(10, 5, 10, 10)

        # Results list
        self.results_list = QListWidget()
        self.results_list.setStyleSheet("""
            QListWidget {
                border: none;
                background-color: transparent;
                color: white;
            }
            QListWidget::item {
                padding: 8px 4px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            }
            QListWidget::item:selected {
                background-color: rgba(65, 135, 230, 0.6);
                border-radius: 5px;
            }
        """)
        self.results_list.itemDoubleClicked.connect(self.open_file)
        self.results_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.results_list.customContextMenuRequested.connect(self.show_context_menu)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("""
            color: rgba(255, 255, 255, 0.5);
            padding: 5px 0px;
            font-size: 12px;
        """)

        # Add widgets to results layout
        self.results_layout.addWidget(self.results_list)
        self.results_layout.addWidget(self.status_label)

        # Add widgets to main layout
        self.main_layout.addWidget(search_container)
        self.main_layout.addWidget(self.results_container)

        # Initialize database connection
        self.conn = sqlite3.connect(DB_PATH)
        self.cursor = self.conn.cursor()

        # Icon cache
        self.file_type_icons = {}

        # Install event filter to close on click outside
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, event):
        """Filter events to detect clicks outside the widget"""
        if event.type() == QEvent.MouseButtonPress:
            if not self.geometry().contains(event.globalPos()):
                self.hide()
                self.closed.emit()
                return True
        return super().eventFilter(obj, event)

    def focusOutEvent(self, event):
        """Hide when focus is lost"""
        # Don't hide if focus moved to a child widget (like the results list)
        if not self.isAncestorOf(QApplication.focusWidget()):
            self.hide()
            self.closed.emit()
        super().focusOutEvent(event)

    def search(self):
        """Search for files based on input text"""
        query = self.search_input.text().strip()
        self.results_list.clear()

        if not query:
            # Hide results container when query is empty
            self.results_container.setVisible(False)
            self.resize(self.fixed_width, self.min_height)
            return

        try:
            # Use LIKE for case-insensitive search
            search_pattern = f"%{query}%"
            self.cursor.execute("""
                SELECT name, path, type FROM files 
                WHERE name LIKE ? 
                ORDER BY name
                LIMIT 100
            """, (search_pattern,))

            results = self.cursor.fetchall()

            for name, path, file_type in results:
                item = QListWidgetItem()

                # Create file info display with icon
                file_icon = self._get_file_icon(file_type)
                if file_icon:
                    item.setIcon(file_icon)

                # Set file name and full path
                item.setText(name)
                item.setToolTip(path)
                item.setData(Qt.UserRole, path)
                self.results_list.addItem(item)

            # Show or hide results container based on results
            has_results = self.results_list.count() > 0
            self.results_container.setVisible(has_results)

            if has_results:
                # Update status label
                self.status_label.setText(f"Found {self.results_list.count()} results")

                # Set the focus to the first item
                if self.results_list.count() > 0:
                    self.results_list.setCurrentRow(0)

                # Calculate height based on number of results (with a maximum)
                results_height = min(
                    self.results_list.count() * 40 + 60,  # Approx height per item + padding
                    self.max_height - self.min_height
                )
                total_height = self.min_height + results_height

                # Resize window to accommodate results
                self.resize(self.fixed_width, total_height)
            else:
                # Just show search bar when no results
                self.resize(self.fixed_width, self.min_height)

        except sqlite3.Error as e:
            self.status_label.setText(f"Search error: {str(e)}")
            self.results_container.setVisible(True)

    def _get_file_icon(self, file_type):
        """Get icon for file type"""
        if not file_type:
            return None

        # Check if icon is in cache
        if file_type in self.file_type_icons:
            return self.file_type_icons[file_type]

        # Try to get system icon
        icon = QIcon.fromTheme("text-x-generic")  # Fallback

        # Cache icon for future use
        self.file_type_icons[file_type] = icon
        return icon

    def open_file(self, item):
        """Open the selected file with default application"""
        file_path = item.data(Qt.UserRole)
        if file_path:
            self.open_path(file_path)
            self.hide()
            self.closed.emit()

    def open_path(self, path):
        """Open file with the default application based on OS"""
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":  # macOS
                os.system(f"open '{path}'")
            else:  # Linux
                os.system(f"xdg-open '{path}'")
        except Exception as e:
            self.status_label.setText(f"Error opening file: {str(e)}")

    def open_location(self, path):
        """Open the folder containing the file"""
        try:
            folder = os.path.dirname(path)
            if sys.platform == "win32":
                os.startfile(folder)
            elif sys.platform == "darwin":  # macOS
                os.system(f"open '{folder}'")
            else:  # Linux
                os.system(f"xdg-open '{folder}'")
        except Exception as e:
            self.status_label.setText(f"Error opening location: {str(e)}")

    def copy_path(self, path):
        """Copy the file path to clipboard"""
        clipboard = QApplication.clipboard()
        clipboard.setText(path)
        self.status_label.setText("Path copied to clipboard")

    def show_context_menu(self, position):
        """Show context menu for file operations"""
        item = self.results_list.itemAt(position)
        if not item:
            return

        file_path = item.data(Qt.UserRole)

        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: rgba(40, 40, 40, 0.95);
                color: white;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 5px;
                padding: 5px;
            }
            QMenu::item {
                padding: 5px 25px 5px 20px;
                border-radius: 3px;
            }
            QMenu::item:selected {
                background-color: rgba(65, 135, 230, 0.6);
            }
        """)

        open_action = QAction("Open", self)
        open_action.triggered.connect(lambda: self.open_path(file_path))

        location_action = QAction("Open Location", self)
        location_action.triggered.connect(lambda: self.open_location(file_path))

        copy_action = QAction("Copy Path", self)
        copy_action.triggered.connect(lambda: self.copy_path(file_path))

        menu.addAction(open_action)
        menu.addAction(location_action)
        menu.addAction(copy_action)

        menu.exec_(QCursor.pos())

    def keyPressEvent(self, event):
        """Handle key press events"""
        if event.key() == Qt.Key_Escape:
            self.hide()
            self.closed.emit()
        elif event.key() == Qt.Key_Return and self.results_list.currentItem():
            self.open_file(self.results_list.currentItem())
        elif event.key() == Qt.Key_Down:
            current = self.results_list.currentRow()
            if current < self.results_list.count() - 1:
                self.results_list.setCurrentRow(current + 1)
        elif event.key() == Qt.Key_Up:
            current = self.results_list.currentRow()
            if current > 0:
                self.results_list.setCurrentRow(current - 1)
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        """Handle close event"""
        self.conn.close()
        event.accept()


class KhojDaSearch:
    """Main application class"""

    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        # Set application name and version
        self.app.setApplicationName("Khoj Da Search")
        self.app.setApplicationVersion("1.0")

        # Create system tray icon
        self.tray_icon = QSystemTrayIcon(self.app)
        self.tray_icon.setToolTip("Khoj Da Search")

        # Create tray menu
        tray_menu = QMenu()

        # Action for re-indexing files
        index_action = QAction("Re-index Files", self.app)
        index_action.triggered.connect(self.reindex_files)

        quit_action = QAction("Quit", self.app)
        quit_action.triggered.connect(self.on_quit)

        tray_menu.addAction(index_action)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

        # Initialize search bar but don't show it yet
        self.search_bar = None
        self.indexing_dialog = None
        self.indexer = None

        # Set up global hotkey listener
        self.hotkey_listener = keyboard.GlobalHotKeys({
            '<alt>+<space>': self.toggle_search_bar
        })
        self.hotkey_listener.start()

        # Always cache/index when application starts
        self.start_indexing(first_time=not os.path.exists(DB_PATH), show_search_after=True)

    def on_quit(self):
        """Clean up resources and quit the application"""
        # Stop indexer if running
        if self.indexer and self.indexer.isRunning():
            self.indexer.stop()
            self.indexer.wait(1000)  # Wait for indexer to stop

        # Close search bar and its database connection
        if self.search_bar:
            if hasattr(self.search_bar, 'conn') and self.search_bar.conn:
                try:
                    self.search_bar.conn.close()
                except:
                    pass

        # Stop hotkey listener
        if self.hotkey_listener:
            self.hotkey_listener.stop()

        # Quit application
        self.app.quit()

    def reindex_files(self):
        """Re-index files (avoiding lambda for clarity)"""
        self.start_indexing(first_time=False)

    def init_search_bar(self):
        """Initialize the search bar"""
        if not self.search_bar:
            self.search_bar = SearchBar()

    def toggle_search_bar(self):
        """Show or hide the search bar"""
        # Make sure search bar is initialized
        if not self.search_bar:
            self.init_search_bar()

        if self.search_bar.isVisible():
            self.search_bar.hide()
        else:
            # Recenter the search bar in the middle of the screen
            screen_geometry = QApplication.desktop().availableGeometry()
            x = (screen_geometry.width() - self.search_bar.fixed_width) // 2
            y = (screen_geometry.height() - self.search_bar.min_height) // 2
            self.search_bar.move(x, y)
            self.search_bar.resize(self.search_bar.fixed_width, self.search_bar.min_height)

            # Clear previous search input and results
            self.search_bar.search_input.clear()
            self.search_bar.results_list.clear()
            self.search_bar.results_container.setVisible(False)

            # Show and focus
            self.search_bar.show()
            self.search_bar.search_input.setFocus()
            self.search_bar.activateWindow()  # Ensure it gets focus

    def start_indexing(self, first_time=False, show_search_after=False):
        """Start file indexing process"""
        self.indexing_dialog = IndexingDialog()
        self.indexing_dialog.show()

        self.indexer = FileIndexer()
        self.indexer.progress_signal.connect(self.indexing_dialog.update_status)

        if first_time or show_search_after:
            # If it's the first time or we should show search after, initialize search bar after indexing
            self.indexer.finished_signal.connect(lambda: self.on_indexing_finished(show_search=True))
        else:
            self.indexer.finished_signal.connect(lambda: self.on_indexing_finished(show_search=False))

        self.indexer.start()

    def on_indexing_finished(self, show_search=False):
        """Handle indexing completion"""
        if self.indexing_dialog:
            self.indexing_dialog.hide()
            self.indexing_dialog = None

        if show_search:
            # Initialize and show search bar
            self.init_search_bar()
            self.toggle_search_bar()  # Show search bar after indexing

    def run(self):
        """Run the application"""
        return self.app.exec_()


if __name__ == "__main__":
    khoj = KhojDaSearch()
    sys.exit(khoj.run())