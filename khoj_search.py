#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Khoj Da Search - A modern cross-platform Spotlight-like search utility
Python 3.8+ with modern PyQt6, efficient indexing, and clean UI
"""

import os
import sys
import json
import sqlite3
import logging
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass, asdict
from contextlib import contextmanager

# Modern Qt5 imports (compatible version)
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, 
    QListWidget, QListWidgetItem, QLabel, QMenu, QSystemTrayIcon,
    QDialog, QProgressBar, QFrame, QScrollArea, QDesktopWidget, QAction
)
from PyQt5.QtCore import (
    Qt, pyqtSignal, QThread, QEvent, QTimer, QSize, QPropertyAnimation, 
    QEasingCurve, QRect, QSettings
)
from PyQt5.QtGui import QIcon, QFont, QCursor

# Global hotkey and file monitoring
from pynput import keyboard
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Application data directory
from appdirs import user_data_dir, user_config_dir


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class AppConfig:
    """Application configuration with sensible defaults"""
    theme: str = "dark"
    hotkey: str = "<alt>+<space>"
    max_results: int = 50
    search_delay_ms: int = 150
    index_hidden_files: bool = False
    auto_update_index: bool = True
    excluded_paths: List[str] = None
    window_opacity: float = 0.95
    animation_duration: int = 200
    
    def __post_init__(self):
        if self.excluded_paths is None:
            self.excluded_paths = [
                "node_modules", ".git", "__pycache__", ".vscode",
                "Library/Caches", "AppData/Local/Temp"
            ]


class ConfigManager:
    """Modern configuration management"""
    
    def __init__(self):
        self.config_dir = Path(user_config_dir("KhojDaSearch", "Khaled"))
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / "config.json"
        self._config = self._load_config()
    
    def _load_config(self) -> AppConfig:
        """Load configuration from file"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                return AppConfig(**data)
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"Failed to load config: {e}. Using defaults.")
        
        return AppConfig()
    
    def save_config(self):
        """Save configuration to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(asdict(self._config), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
    
    @property
    def config(self) -> AppConfig:
        return self._config


class DatabaseManager:
    """Efficient database operations with connection pooling"""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_database()
    
    def _init_database(self):
        """Initialize database with optimized schema"""
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL UNIQUE,
                    parent_path TEXT NOT NULL,
                    extension TEXT,
                    size INTEGER,
                    modified_time INTEGER,
                    indexed_time INTEGER,
                    is_directory BOOLEAN DEFAULT 0
                );
                
                CREATE INDEX IF NOT EXISTS idx_name ON files(name);
                CREATE INDEX IF NOT EXISTS idx_parent ON files(parent_path);
                CREATE INDEX IF NOT EXISTS idx_extension ON files(extension);
                CREATE INDEX IF NOT EXISTS idx_modified ON files(modified_time);
                CREATE INDEX IF NOT EXISTS idx_path ON files(path);
                
                -- Full-text search support
                CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
                    name, path, content='files', content_rowid='id'
                );
                
                -- Triggers to keep FTS in sync
                CREATE TRIGGER IF NOT EXISTS files_fts_insert AFTER INSERT ON files BEGIN
                    INSERT INTO files_fts(rowid, name, path) VALUES (new.id, new.name, new.path);
                END;
                
                CREATE TRIGGER IF NOT EXISTS files_fts_delete AFTER DELETE ON files BEGIN
                    DELETE FROM files_fts WHERE rowid = old.id;
                END;
                
                CREATE TRIGGER IF NOT EXISTS files_fts_update AFTER UPDATE ON files BEGIN
                    DELETE FROM files_fts WHERE rowid = old.id;
                    INSERT INTO files_fts(rowid, name, path) VALUES (new.id, new.name, new.path);
                END;
            """)
    
    @contextmanager
    def _get_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=10000")
        conn.execute("PRAGMA temp_store=MEMORY")
        
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def batch_insert_files(self, files_data: List[Tuple]) -> int:
        """Efficiently insert multiple files"""
        with self._lock, self._get_connection() as conn:
            conn.executemany("""
                INSERT OR REPLACE INTO files 
                (name, path, parent_path, extension, size, modified_time, indexed_time, is_directory)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, files_data)
            return conn.total_changes
    
    def search_files(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Fast file search using FTS and fuzzy matching"""
        with self._get_connection() as conn:
            # Try FTS search first for exact matches
            fts_results = conn.execute("""
                SELECT f.name, f.path, f.parent_path, f.extension, f.size, 
                       f.modified_time, f.is_directory,
                       rank * -1 as relevance
                FROM files_fts 
                JOIN files f ON files_fts.rowid = f.id
                WHERE files_fts MATCH ?
                ORDER BY relevance DESC
                LIMIT ?
            """, (f'"{query}"*', limit // 2)).fetchall()
            
            # Fuzzy search for partial matches
            fuzzy_query = f"%{query.replace(' ', '%')}%"
            fuzzy_results = conn.execute("""
                SELECT name, path, parent_path, extension, size, 
                       modified_time, is_directory,
                       0 as relevance
                FROM files 
                WHERE name LIKE ? 
                AND path NOT IN (SELECT path FROM files_fts WHERE files_fts MATCH ?)
                ORDER BY name
                LIMIT ?
            """, (fuzzy_query, f'"{query}"*', limit // 2)).fetchall()
            
            # Combine and format results
            all_results = fts_results + fuzzy_results
            return [
                {
                    'name': row[0], 'path': row[1], 'parent_path': row[2],
                    'extension': row[3], 'size': row[4], 'modified_time': row[5],
                    'is_directory': bool(row[6]), 'relevance': row[7]
                }
                for row in all_results[:limit]
            ]
    
    def get_file_count(self) -> int:
        """Get total number of indexed files"""
        with self._get_connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    
    def remove_file(self, path: str):
        """Remove a file from the index"""
        with self._lock, self._get_connection() as conn:
            conn.execute("DELETE FROM files WHERE path = ?", (path,))
    
    def get_stale_files(self, cutoff_time: int) -> List[str]:
        """Get files that haven't been updated since cutoff_time"""
        with self._get_connection() as conn:
            results = conn.execute(
                "SELECT path FROM files WHERE indexed_time < ?", 
                (cutoff_time,)
            ).fetchall()
            return [row[0] for row in results]


class FileWatcher(FileSystemEventHandler):
    """Monitor filesystem changes for incremental updates"""
    
    def __init__(self, indexer_callback):
        self.indexer_callback = indexer_callback
        self._debounce_timer = {}
    
    def on_any_event(self, event):
        """Handle filesystem events with debouncing"""
        if event.is_directory:
            return
            
        path = event.src_path
        
        # Cancel previous timer for this path
        if path in self._debounce_timer:
            self._debounce_timer[path].stop()
        
        # Create new debounced timer
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._handle_file_change(event))
        timer.start(1000)  # 1 second debounce
        
        self._debounce_timer[path] = timer
    
    def _handle_file_change(self, event):
        """Handle debounced file change"""
        self.indexer_callback(event.src_path, event.event_type)


class FileIndexer(QThread):
    """Modern file indexer with incremental updates and progress tracking"""
    
    progress_signal = pyqtSignal(str, int, int)  # message, current, total
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)
    
    def __init__(self, db_manager: DatabaseManager, config: AppConfig):
        super().__init__()
        self.db_manager = db_manager
        self.config = config
        self.should_stop = False
        self.current_files = 0
        self.total_files = 0
        
        # File monitoring
        self.observer = Observer()
        self.file_watcher = FileWatcher(self._handle_file_change)
    
    def run(self):
        """Main indexing process"""
        try:
            self._index_files()
            if self.config.auto_update_index:
                self._start_file_monitoring()
        except Exception as e:
            logger.error(f"Indexing failed: {e}")
            self.error_signal.emit(str(e))
        finally:
            self.finished_signal.emit()
    
    def stop(self):
        """Stop indexing process"""
        self.should_stop = True
        if hasattr(self, 'observer'):
            self.observer.stop()
    
    def _index_files(self):
        """Index files with progress tracking"""
        start_time = int(datetime.now().timestamp())
        
        # Get directories to scan
        scan_paths = self._get_scan_paths()
        
        # Estimate total files
        self.progress_signal.emit("Estimating files to index...", 0, 0)
        self.total_files = self._estimate_total_files(scan_paths)
        
        # Process files in batches
        batch_size = 1000
        batch_data = []
        
        for scan_path in scan_paths:
            if self.should_stop:
                break
                
            for file_info in self._walk_directory(scan_path):
                if self.should_stop:
                    break
                
                batch_data.append((*file_info, start_time))
                self.current_files += 1
                
                if len(batch_data) >= batch_size:
                    self.db_manager.batch_insert_files(batch_data)
                    batch_data = []
                    
                    # Update progress
                    progress = min(99, int(self.current_files / max(1, self.total_files) * 100))
                    self.progress_signal.emit(
                        f"Indexed {self.current_files:,} files",
                        self.current_files,
                        self.total_files
                    )
        
        # Insert remaining files
        if batch_data:
            self.db_manager.batch_insert_files(batch_data)
        
        # Clean up stale files
        stale_files = self.db_manager.get_stale_files(start_time)
        for file_path in stale_files:
            self.db_manager.remove_file(file_path)
        
        self.progress_signal.emit(
            f"Completed! Indexed {self.current_files:,} files",
            self.current_files,
            self.current_files
        )
    
    def _get_scan_paths(self) -> List[Path]:
        """Get paths to scan based on platform"""
        if sys.platform == "win32":
            import ctypes
            drives = []
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for letter in range(65, 91):  # A-Z
                if bitmask & 1:
                    drives.append(Path(f"{chr(letter)}:\\"))
                bitmask >>= 1
            return drives
        else:
            # Unix-like systems
            common_paths = [
                Path.home(),
                Path("/usr/local"),
                Path("/opt"),
                Path("/Applications") if sys.platform == "darwin" else Path("/usr/share")
            ]
            return [p for p in common_paths if p.exists()]
    
    def _estimate_total_files(self, scan_paths: List[Path]) -> int:
        """Efficiently estimate total files to index"""
        total_estimate = 0
        sample_limit = 5000  # Sample first 5000 files for estimation
        
        for path in scan_paths:
            try:
                sample_count = 0
                dir_count = 0
                
                for item in path.rglob("*"):
                    if self.should_stop or sample_count >= sample_limit:
                        break
                    
                    if self._should_skip_path(item):
                        continue
                    
                    if item.is_dir():
                        dir_count += 1
                    else:
                        sample_count += 1
                
                # Extrapolate based on directory structure
                if dir_count > 0 and sample_count > 0:
                    avg_files_per_dir = sample_count / dir_count
                    estimated_dirs = dir_count * 3  # Rough multiplier
                    total_estimate += int(avg_files_per_dir * estimated_dirs)
                else:
                    total_estimate += sample_count * 2
                    
            except (PermissionError, OSError):
                continue
        
        return max(1000, total_estimate)
    
    def _walk_directory(self, path: Path):
        """Generator that yields file information"""
        try:
            for item in path.rglob("*"):
                if self.should_stop:
                    break
                
                if self._should_skip_path(item):
                    continue
                
                try:
                    stat_info = item.stat()
                    yield (
                        item.name,                                    # name
                        str(item.absolute()),                         # path
                        str(item.parent.absolute()),                  # parent_path
                        item.suffix.lower() if item.suffix else "",  # extension
                        stat_info.st_size,                           # size
                        int(stat_info.st_mtime),                     # modified_time
                        item.is_dir()                                # is_directory
                    )
                except (PermissionError, OSError, ValueError):
                    continue
                    
        except (PermissionError, OSError):
            logger.warning(f"Cannot access directory: {path}")
    
    def _should_skip_path(self, path: Path) -> bool:
        """Check if path should be skipped during indexing"""
        # Skip hidden files/directories unless configured otherwise
        if not self.config.index_hidden_files and path.name.startswith('.'):
            return True
        
        # Skip system directories and common exclusions
        path_str = str(path)
        for excluded in self.config.excluded_paths:
            if excluded in path_str:
                return True
        
        return False
    
    def _start_file_monitoring(self):
        """Start monitoring filesystem changes"""
        try:
            scan_paths = self._get_scan_paths()
            for path in scan_paths:
                if path.exists():
                    self.observer.schedule(self.file_watcher, str(path), recursive=True)
            
            self.observer.start()
            logger.info("File monitoring started")
        except Exception as e:
            logger.error(f"Failed to start file monitoring: {e}")
    
    def _handle_file_change(self, file_path: str, event_type: str):
        """Handle individual file changes"""
        # This could trigger incremental updates
        logger.debug(f"File {event_type}: {file_path}")


class ModernSearchBar(QWidget):
    """Modern, animated search interface with enhanced UX"""
    
    closed = pyqtSignal()
    
    def __init__(self, db_manager: DatabaseManager, config: AppConfig):
        super().__init__()
        self.db_manager = db_manager
        self.config = config
        
        self._setup_window()
        self._create_ui()
        self._setup_search_timer()
        self._setup_animations()
        
        # Install global event filter
        QApplication.instance().installEventFilter(self)
    
    def _setup_window(self):
        """Configure window properties"""
        self.setWindowFlags(
            Qt.FramelessWindowHint | 
            Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Calculate size and position
        screen = QDesktopWidget().availableGeometry()
        self.search_width = int(screen.width() * 0.4)
        self.search_height = 60
        self.max_height = int(screen.height() * 0.7)
        
        # Position at screen center
        x = (screen.width() - self.search_width) // 2
        y = (screen.height() - self.search_height) // 2
        self.setGeometry(x, y, self.search_width, self.search_height)
        
        # Set window opacity
        self.setWindowOpacity(self.config.window_opacity)
    
    def _create_ui(self):
        """Create modern UI elements"""
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(8)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Main container with modern styling
        self.container = QFrame()
        self.container.setObjectName("searchContainer")
        self.container.setStyleSheet(self._get_modern_styles())
        
        container_layout = QVBoxLayout(self.container)
        container_layout.setSpacing(0)
        container_layout.setContentsMargins(0, 0, 0, 0)
        
        # Search input section
        search_section = self._create_search_section()
        container_layout.addWidget(search_section)
        
        # Results section (initially hidden)
        self.results_section = self._create_results_section()
        self.results_section.setVisible(False)
        container_layout.addWidget(self.results_section)
        
        self.main_layout.addWidget(self.container)
    
    def _create_search_section(self) -> QFrame:
        """Create the search input section"""
        section = QFrame()
        section.setFixedHeight(60)
        section.setObjectName("searchSection")
        
        layout = QHBoxLayout(section)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(15)
        
        # Search icon
        icon_label = QLabel("🔍")
        icon_label.setObjectName("searchIcon")
        icon_label.setFixedSize(24, 24)
        layout.addWidget(icon_label)
        
        # Search input
        self.search_input = QLineEdit()
        self.search_input.setObjectName("searchInput")
        self.search_input.setPlaceholderText("Search files and folders...")
        self.search_input.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.search_input)
        
        return section
    
    def _create_results_section(self) -> QFrame:
        """Create the results display section"""
        section = QFrame()
        section.setObjectName("resultsSection")
        
        layout = QVBoxLayout(section)
        layout.setContentsMargins(10, 5, 10, 10)
        layout.setSpacing(5)
        
        # Results list
        self.results_list = QListWidget()
        self.results_list.setObjectName("resultsList")
        self.results_list.itemDoubleClicked.connect(self._open_file)
        self.results_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.results_list.customContextMenuRequested.connect(self._show_context_menu)
        
        # Status label
        self.status_label = QLabel()
        self.status_label.setObjectName("statusLabel")
        
        layout.addWidget(self.results_list)
        layout.addWidget(self.status_label)
        
        return section
    
    def _setup_search_timer(self):
        """Setup debounced search timer"""
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._perform_search)
    
    def _setup_animations(self):
        """Setup smooth animations"""
        self.resize_animation = QPropertyAnimation(self, b"geometry")
        self.resize_animation.setDuration(self.config.animation_duration)
        self.resize_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    
    def _get_modern_styles(self) -> str:
        """Get modern CSS styling"""
        if self.config.theme == "dark":
            return """
                QFrame#searchContainer {
                    background: rgba(45, 45, 48, 0.95);
                    border: 1px solid rgba(76, 76, 80, 0.8);
                    border-radius: 12px;
                }
                
                QFrame#searchSection {
                    background: transparent;
                    border: none;
                    border-bottom: 1px solid rgba(76, 76, 80, 0.5);
                }
                
                QLabel#searchIcon {
                    color: rgba(255, 255, 255, 0.8);
                    font-size: 18px;
                }
                
                QLineEdit#searchInput {
                    background: transparent;
                    border: none;
                    color: #ffffff;
                    font-size: 16px;
                    font-weight: 400;
                    padding: 8px 0px;
                }
                
                QLineEdit#searchInput::placeholder {
                    color: rgba(255, 255, 255, 0.5);
                }
                
                QFrame#resultsSection {
                    background: transparent;
                    border: none;
                }
                
                QListWidget#resultsList {
                    background: transparent;
                    border: none;
                    color: #ffffff;
                    outline: none;
                }
                
                QListWidget#resultsList::item {
                    padding: 10px 8px;
                    border-radius: 6px;
                    margin: 2px;
                }
                
                QListWidget#resultsList::item:selected {
                    background: rgba(0, 122, 255, 0.3);
                }
                
                QListWidget#resultsList::item:hover {
                    background: rgba(255, 255, 255, 0.1);
                }
                
                QLabel#statusLabel {
                    color: rgba(255, 255, 255, 0.6);
                    font-size: 12px;
                    padding: 5px 8px;
                }
            """
        else:
            # Light theme
            return """
                QFrame#searchContainer {
                    background: rgba(255, 255, 255, 0.95);
                    border: 1px solid rgba(200, 200, 200, 0.8);
                    border-radius: 12px;
                }
                
                QFrame#searchSection {
                    background: transparent;
                    border: none;
                    border-bottom: 1px solid rgba(200, 200, 200, 0.5);
                }
                
                QLabel#searchIcon {
                    color: rgba(0, 0, 0, 0.8);
                    font-size: 18px;
                }
                
                QLineEdit#searchInput {
                    background: transparent;
                    border: none;
                    color: #000000;
                    font-size: 16px;
                    font-weight: 400;
                    padding: 8px 0px;
                }
                
                QLineEdit#searchInput::placeholder {
                    color: rgba(0, 0, 0, 0.5);
                }
                
                QFrame#resultsSection {
                    background: transparent;
                    border: none;
                }
                
                QListWidget#resultsList {
                    background: transparent;
                    border: none;
                    color: #000000;
                    outline: none;
                }
                
                QListWidget#resultsList::item {
                    padding: 10px 8px;
                    border-radius: 6px;
                    margin: 2px;
                }
                
                QListWidget#resultsList::item:selected {
                    background: rgba(0, 122, 255, 0.3);
                }
                
                QListWidget#resultsList::item:hover {
                    background: rgba(0, 0, 0, 0.1);
                }
                
                QLabel#statusLabel {
                    color: rgba(0, 0, 0, 0.6);
                    font-size: 12px;
                    padding: 5px 8px;
                }
            """
    
    def _on_text_changed(self):
        """Handle search text changes with debouncing"""
        self.search_timer.stop()
        self.search_timer.start(self.config.search_delay_ms)
    
    def _perform_search(self):
        """Perform the actual search"""
        query = self.search_input.text().strip()
        self.results_list.clear()
        
        if not query:
            self._hide_results()
            return
        
        try:
            # Search database
            results = self.db_manager.search_files(query, self.config.max_results)
            
            if not results:
                self.status_label.setText("No results found")
                self._show_results()
                return
            
            # Populate results
            for result in results:
                item = QListWidgetItem()
                
                # Format display text
                name = result['name']
                path = result['parent_path']
                
                # Add file type icon (simplified)
                icon_text = "📁" if result['is_directory'] else self._get_file_icon(result['extension'])
                display_text = f"{icon_text}  {name}"
                
                item.setText(display_text)
                item.setToolTip(result['path'])
                item.setData(Qt.UserRole, result)
                
                self.results_list.addItem(item)
            
            # Update status and show results
            self.status_label.setText(f"{len(results)} results")
            self._show_results()
            
            # Select first item
            if self.results_list.count() > 0:
                self.results_list.setCurrentRow(0)
                
        except Exception as e:
            logger.error(f"Search error: {e}")
            self.status_label.setText("Search error occurred")
            self._show_results()
    
    def _get_file_icon(self, extension: str) -> str:
        """Get emoji icon for file extension"""
        icon_map = {
            '.py': '🐍', '.js': '📜', '.html': '🌐', '.css': '🎨', '.json': '📋',
            '.txt': '📄', '.md': '📝', '.pdf': '📚', '.doc': '📄', '.docx': '📄',
            '.xls': '📊', '.xlsx': '📊', '.ppt': '📽️', '.pptx': '📽️',
            '.jpg': '🖼️', '.jpeg': '🖼️', '.png': '🖼️', '.gif': '🖼️', '.svg': '🖼️',
            '.mp3': '🎵', '.wav': '🎵', '.mp4': '🎬', '.avi': '🎬', '.mov': '🎬',
            '.zip': '🗜️', '.rar': '🗜️', '.7z': '🗜️', '.tar': '🗜️', '.gz': '🗜️',
            '.exe': '⚙️', '.app': '📱', '.deb': '📦', '.rpm': '📦',
        }
        return icon_map.get(extension.lower(), '📄')
    
    def _show_results(self):
        """Show results section with animation"""
        if self.results_section.isVisible():
            return
        
        self.results_section.setVisible(True)
        
        # Calculate new height based on results
        results_count = min(self.results_list.count(), 8)  # Max 8 visible items
        new_height = self.search_height + (results_count * 50) + 60  # Padding
        new_height = min(new_height, self.max_height)
        
        # Animate resize
        current_geometry = self.geometry()
        new_geometry = QRect(
            current_geometry.x(),
            current_geometry.y(),
            current_geometry.width(),
            new_height
        )
        
        self.resize_animation.setStartValue(current_geometry)
        self.resize_animation.setEndValue(new_geometry)
        self.resize_animation.start()
    
    def _hide_results(self):
        """Hide results section with animation"""
        if not self.results_section.isVisible():
            return
        
        # Animate back to search-only size
        current_geometry = self.geometry()
        new_geometry = QRect(
            current_geometry.x(),
            current_geometry.y(),
            current_geometry.width(),
            self.search_height
        )
        
        self.resize_animation.setStartValue(current_geometry)
        self.resize_animation.setEndValue(new_geometry)
        self.resize_animation.finished.connect(
            lambda: self.results_section.setVisible(False)
        )
        self.resize_animation.start()
    
    def _open_file(self, item: QListWidgetItem):
        """Open selected file"""
        result = item.data(Qt.UserRole)
        if result:
            self._open_path(result['path'])
            self.hide()
            self.closed.emit()
    
    def _open_path(self, path: str):
        """Open path with system default application"""
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                os.system(f"open '{path}'")
            else:
                os.system(f"xdg-open '{path}'")
        except Exception as e:
            logger.error(f"Failed to open path {path}: {e}")
    
    def _show_context_menu(self, position):
        """Show context menu for file operations"""
        item = self.results_list.itemAt(position)
        if not item:
            return
        
        result = item.data(Qt.UserRole)
        file_path = result['path']
        
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: rgba(50, 50, 53, 0.95);
                color: white;
                border: 1px solid rgba(76, 76, 80, 0.8);
                border-radius: 8px;
                padding: 8px 0px;
            }
            QMenu::item {
                padding: 8px 16px;
                margin: 2px 8px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: rgba(0, 122, 255, 0.3);
            }
        """)
        
        # Menu actions
        open_action = QAction("Open", self)
        open_action.triggered.connect(lambda: self._open_path(file_path))
        
        reveal_action = QAction("Show in Folder", self)
        reveal_action.triggered.connect(lambda: self._reveal_in_folder(file_path))
        
        copy_action = QAction("Copy Path", self)
        copy_action.triggered.connect(lambda: self._copy_path(file_path))
        
        menu.addAction(open_action)
        menu.addAction(reveal_action)
        menu.addSeparator()
        menu.addAction(copy_action)
        
        menu.exec(QCursor.pos())
    
    def _reveal_in_folder(self, path: str):
        """Reveal file in folder"""
        try:
            folder = os.path.dirname(path)
            if sys.platform == "win32":
                os.system(f'explorer /select,"{path}"')
            elif sys.platform == "darwin":
                os.system(f'open -R "{path}"')
            else:
                os.system(f'xdg-open "{folder}"')
        except Exception as e:
            logger.error(f"Failed to reveal path {path}: {e}")
    
    def _copy_path(self, path: str):
        """Copy file path to clipboard"""
        clipboard = QApplication.clipboard()
        clipboard.setText(path)
        self.status_label.setText("Path copied to clipboard")
    
    def keyPressEvent(self, event):
        """Handle keyboard navigation"""
        if event.key() == Qt.Key_Escape:
            self.hide()
            self.closed.emit()
        elif event.key() == Qt.Key_Return:
            current_item = self.results_list.currentItem()
            if current_item:
                self._open_file(current_item)
        elif event.key() == Qt.Key_Down:
            if self.results_list.count() > 0:
                current_row = self.results_list.currentRow()
                if current_row < self.results_list.count() - 1:
                    self.results_list.setCurrentRow(current_row + 1)
        elif event.key() == Qt.Key_Up:
            if self.results_list.count() > 0:
                current_row = self.results_list.currentRow()
                if current_row > 0:
                    self.results_list.setCurrentRow(current_row - 1)
        else:
            super().keyPressEvent(event)
    
    def eventFilter(self, obj, event):
        """Handle click outside to close"""
        if event.type() == QEvent.MouseButtonPress:
            if not self.geometry().contains(event.globalPos()):
                self.hide()
                self.closed.emit()
                return True
        return super().eventFilter(obj, event)
    
    def show_and_focus(self):
        """Show window and focus search input"""
        # Clear previous search
        self.search_input.clear()
        self.results_list.clear()
        self._hide_results()
        
        # Show and focus
        self.show()
        self.search_input.setFocus()
        self.activateWindow()
        self.raise_()


class ModernIndexingDialog(QDialog):
    """Modern indexing progress dialog"""
    
    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self._setup_dialog()
        self._create_ui()
    
    def _setup_dialog(self):
        """Setup dialog properties"""
        self.setWindowTitle("Khoj Da Search")
        self.setFixedSize(480, 200)
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | 
            Qt.FramelessWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Center on screen
        screen = QDesktopWidget().availableGeometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)
    
    def _create_ui(self):
        """Create modern UI"""
        layout = QVBoxLayout(self)
        
        # Main container
        container = QFrame()
        container.setStyleSheet("""
            QFrame {
                background: rgba(45, 45, 48, 0.95);
                border: 1px solid rgba(76, 76, 80, 0.8);
                border-radius: 16px;
            }
        """)
        
        container_layout = QVBoxLayout(container)
        container_layout.setSpacing(20)
        container_layout.setContentsMargins(40, 30, 40, 30)
        
        # Title
        title = QLabel("🔍 Khoj Da Search")
        title.setStyleSheet("""
            color: white;
            font-size: 24px;
            font-weight: 600;
            qproperty-alignment: AlignCenter;
        """)
        
        # Status message
        self.status_label = QLabel("Preparing to index files...")
        self.status_label.setStyleSheet("""
            color: rgba(255, 255, 255, 0.8);
            font-size: 14px;
            qproperty-alignment: AlignCenter;
        """)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                border-radius: 8px;
                background-color: rgba(76, 76, 80, 0.5);
                color: white;
                text-align: center;
                font-weight: 500;
                height: 20px;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, 
                    stop:0 rgba(0, 122, 255, 0.8), 
                    stop:1 rgba(88, 86, 214, 0.8));
                border-radius: 8px;
            }
        """)
        
        # Info text
        info = QLabel("Building search index for faster file discovery")
        info.setStyleSheet("""
            color: rgba(255, 255, 255, 0.6);
            font-size: 12px;
            qproperty-alignment: AlignCenter;
        """)
        
        # Add to layout
        container_layout.addWidget(title)
        container_layout.addWidget(self.status_label)
        container_layout.addWidget(self.progress_bar)
        container_layout.addWidget(info)
        
        layout.addWidget(container)
    
    def update_progress(self, message: str, current: int, total: int):
        """Update progress display"""
        self.status_label.setText(message)
        
        if total > 0:
            progress = min(100, int(current / total * 100))
            self.progress_bar.setValue(progress)
            self.progress_bar.setFormat(f"{progress}% ({current:,} / {total:,})")
        else:
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("Preparing...")


class ModernKhojSearch:
    """Main application class with modern architecture"""
    
    def __init__(self):
        # Initialize application
        self.app = QApplication(sys.argv)
        self.app.setApplicationName("Khoj Da Search")
        self.app.setApplicationVersion("2.0")
        self.app.setQuitOnLastWindowClosed(False)
        
        # Load configuration
        self.config_manager = ConfigManager()
        self.config = self.config_manager.config
        
        # Initialize database
        data_dir = Path(user_data_dir("KhojDaSearch", "Khaled"))
        self.db_manager = DatabaseManager(data_dir / "search_index.db")
        
        # Initialize components
        self.search_bar = None
        self.indexing_dialog = None
        self.indexer = None
        self.hotkey_listener = None
        self.is_indexing = False
        
        # Setup system tray with indexing status
        self._setup_system_tray()
        
        # Setup global hotkey
        self._setup_hotkey()
        
        # Initialize search bar immediately (non-blocking)
        self._initialize_search_bar()
        
        # Start background indexing (after tray is set up)
        QTimer.singleShot(100, self._start_background_indexing)
    
    def _setup_system_tray(self):
        """Setup modern system tray with indexing status"""
        self.tray_icon = QSystemTrayIcon(self.app)
        self.tray_icon.setToolTip("Khoj Da Search - Initializing...")
        
        # Create tray menu
        self.tray_menu = QMenu()
        self.tray_menu.setStyleSheet("""
            QMenu {
                background-color: rgba(50, 50, 53, 0.95);
                color: white;
                border: 1px solid rgba(76, 76, 80, 0.8);
                border-radius: 8px;
                padding: 8px 0px;
            }
            QMenu::item {
                padding: 8px 16px;
                margin: 2px 8px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: rgba(0, 122, 255, 0.3);
            }
            QMenu::item:disabled {
                color: rgba(255, 255, 255, 0.4);
            }
        """)
        
        # Status action (shows current indexing state)
        self.status_action = QAction("🔍 Ready", self.app)
        self.status_action.setEnabled(False)  # Status display only
        
        # Menu actions
        search_action = QAction("🔍 Open Search", self.app)
        search_action.triggered.connect(self.show_search)
        
        self.reindex_action = QAction("🔄 Reindex Files", self.app)
        self.reindex_action.triggered.connect(self.reindex_files)
        
        settings_action = QAction("⚙️ Settings", self.app)
        settings_action.triggered.connect(self.show_settings)
        
        # Show/Hide indexing progress action
        self.progress_action = QAction("📊 Show Progress", self.app)
        self.progress_action.triggered.connect(self._toggle_progress_dialog)
        self.progress_action.setVisible(False)  # Hidden until indexing starts
        
        quit_action = QAction("❌ Quit", self.app)
        quit_action.triggered.connect(self.quit_application)
        
        # Build menu
        self.tray_menu.addAction(self.status_action)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(search_action)
        self.tray_menu.addAction(self.progress_action)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(self.reindex_action)
        self.tray_menu.addAction(settings_action)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()
    
    def _update_tray_icon_status(self, status: str, progress: int = 0):
        """Update tray icon and tooltip based on indexing status"""
        if status == "indexing":
            # Show progress in tooltip
            tooltip = f"Khoj Da Search - Indexing files ({progress}%)"
            self.tray_icon.setToolTip(tooltip)
            if hasattr(self, 'status_action'):
                self.status_action.setText(f"🔄 Indexing ({progress}%)")
                self.reindex_action.setEnabled(False)
                self.progress_action.setVisible(True)
        elif status == "ready":
            try:
                file_count = self.db_manager.get_file_count()
                tooltip = f"Khoj Da Search - Ready ({file_count:,} files indexed)"
                self.tray_icon.setToolTip(tooltip)
                if hasattr(self, 'status_action'):
                    self.status_action.setText(f"✅ Ready ({file_count:,} files)")
                    self.reindex_action.setEnabled(True)
                    self.progress_action.setVisible(False)
            except Exception as e:
                logger.warning(f"Could not get file count: {e}")
                self.tray_icon.setToolTip("Khoj Da Search - Ready")
                if hasattr(self, 'status_action'):
                    self.status_action.setText("✅ Ready")
        elif status == "error":
            self.tray_icon.setToolTip("Khoj Da Search - Error occurred during indexing")
            if hasattr(self, 'status_action'):
                self.status_action.setText("❌ Error occurred")
                self.reindex_action.setEnabled(True)
                self.progress_action.setVisible(False)
    
    def _setup_hotkey(self):
        """Setup global hotkey listener"""
        try:
            hotkey_combination = self.config.hotkey
            self.hotkey_listener = keyboard.GlobalHotKeys({
                hotkey_combination: self.show_search
            })
            self.hotkey_listener.start()
            logger.info(f"Global hotkey registered: {hotkey_combination}")
        except Exception as e:
            logger.error(f"Failed to setup hotkey: {e}")
    
    def _start_background_indexing(self):
        """Start background file indexing with optional UI"""
        needs_indexing = self.db_manager.get_file_count() == 0
        
        if needs_indexing:  # Only index if needed
            self.is_indexing = True
            self._update_tray_icon_status("indexing", 0)
            
            # Show progress dialog for initial indexing (first-time experience)
            self.indexing_dialog = ModernIndexingDialog(self.config)
            self.indexing_dialog.show()  # Show for first-time indexing
            
            # Update progress action to reflect dialog is visible
            if hasattr(self, 'progress_action'):
                self.progress_action.setText("📊 Hide Progress")
            
            # Start background indexer
            self.indexer = FileIndexer(self.db_manager, self.config)
            self.indexer.progress_signal.connect(self._on_indexing_progress)
            self.indexer.finished_signal.connect(self._on_indexing_finished)
            self.indexer.error_signal.connect(self._on_indexing_error)
            self.indexer.start()
        else:
            self._update_tray_icon_status("ready")
    
    def _initialize_search_bar(self):
        """Initialize the search interface"""
        if not self.search_bar:
            self.search_bar = ModernSearchBar(self.db_manager, self.config)
    
    def _on_tray_activated(self, reason):
        """Handle system tray activation"""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_search()
    
    def _on_indexing_progress(self, message: str, current: int, total: int):
        """Handle indexing progress updates"""
        progress = 0
        if total > 0:
            progress = min(99, int(current / total * 100))
        
        # Update tray icon status
        self._update_tray_icon_status("indexing", progress)
        
        # Update progress dialog if visible
        if self.indexing_dialog and self.indexing_dialog.isVisible():
            self.indexing_dialog.update_progress(message, current, total)
    
    def _on_indexing_finished(self):
        """Handle indexing completion"""
        self.is_indexing = False
        self._update_tray_icon_status("ready")
        
        # Hide progress dialog
        if self.indexing_dialog:
            self.indexing_dialog.hide()
        
        logger.info("Background file indexing completed successfully")
    
    def _on_indexing_error(self, error_msg: str):
        """Handle indexing errors"""
        self.is_indexing = False
        self._update_tray_icon_status("error")
        
        logger.error(f"Indexing error: {error_msg}")
        if self.indexing_dialog and self.indexing_dialog.isVisible():
            self.indexing_dialog.status_label.setText(f"Error: {error_msg}")
    
    def _toggle_progress_dialog(self):
        """Show/hide the indexing progress dialog"""
        if self.indexing_dialog:
            if self.indexing_dialog.isVisible():
                self.indexing_dialog.hide()
                self.progress_action.setText("📊 Show Progress")
            else:
                self.indexing_dialog.show()
                self.progress_action.setText("📊 Hide Progress")
    
    def show_search(self):
        """Show the search interface"""
        if not self.search_bar:
            self._initialize_search_bar()
        
        if self.search_bar.isVisible():
            self.search_bar.hide()
        else:
            self.search_bar.show_and_focus()
    
    def reindex_files(self):
        """Trigger file reindexing in background"""
        if self.is_indexing:
            return  # Already indexing
        
        self.is_indexing = True
        self._update_tray_icon_status("indexing", 0)
        
        # Show progress dialog for manual reindexing
        if not self.indexing_dialog:
            self.indexing_dialog = ModernIndexingDialog(self.config)
        
        self.indexing_dialog.show()
        self.progress_action.setText("📊 Hide Progress")
        
        # Start indexer
        self.indexer = FileIndexer(self.db_manager, self.config)
        self.indexer.progress_signal.connect(self._on_indexing_progress)
        self.indexer.finished_signal.connect(self._on_indexing_finished)
        self.indexer.error_signal.connect(self._on_indexing_error)
        self.indexer.start()
    
    def show_settings(self):
        """Show settings dialog (placeholder)"""
        # TODO: Implement settings dialog
        logger.info("Settings dialog not implemented yet")
    
    def quit_application(self):
        """Clean shutdown of the application"""
        logger.info("Shutting down application...")
        
        # Stop indexer
        if self.indexer and self.indexer.isRunning():
            self.indexer.stop()
            self.indexer.wait(3000)  # Wait up to 3 seconds
        
        # Stop hotkey listener
        if self.hotkey_listener:
            self.hotkey_listener.stop()
        
        # Save configuration
        self.config_manager.save_config()
        
        # Quit application
        self.app.quit()
    
    def run(self) -> int:
        """Run the application event loop"""
        logger.info("Starting Khoj Da Search v2.0")
        return self.app.exec()


def main():
    """Application entry point"""
    try:
        app = ModernKhojSearch()
        return app.run()
    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
        return 0
    except Exception as e:
        logger.error(f"Application crashed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())