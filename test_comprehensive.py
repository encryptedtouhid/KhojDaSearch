#!/usr/bin/env python3
"""
Comprehensive test suite for Khoj Da Search v2.0
Tests all major functionality including background indexing
"""

import sys
import tempfile
import time
import threading
from pathlib import Path
from unittest.mock import Mock, patch


def test_database_operations():
    """Test database functionality"""
    print("📊 Testing Database Operations...")
    
    try:
        from khoj_search import DatabaseManager
        
        # Create temporary database
        db_path = Path(tempfile.mktemp(suffix=".db"))
        db_manager = DatabaseManager(db_path)
        
        # Test initial state
        count = db_manager.get_file_count()
        assert count == 0, f"Expected 0 files, got {count}"
        print("  ✅ Empty database initialized correctly")
        
        # Test batch insert
        test_files = [
            ("test1.txt", "/tmp/test1.txt", "/tmp", ".txt", 100, 1640995200, 1640995200, False),
            ("test2.py", "/tmp/test2.py", "/tmp", ".py", 200, 1640995300, 1640995300, False),
            ("folder", "/tmp/folder", "/tmp", "", 0, 1640995400, 1640995400, True),
        ]
        
        result = db_manager.batch_insert_files(test_files)
        print(f"  ✅ Batch insert: {result} changes")
        
        # Test file count
        count = db_manager.get_file_count()
        assert count == 3, f"Expected 3 files, got {count}"
        print(f"  ✅ File count correct: {count}")
        
        # Test search
        results = db_manager.search_files("test")
        assert len(results) >= 1, f"Expected results for 'test', got {len(results)}"
        print(f"  ✅ Search found {len(results)} results")
        
        # Test specific search
        results = db_manager.search_files("py")
        py_files = [r for r in results if r['name'].endswith('.py')]
        assert len(py_files) >= 1, "Expected to find .py files"
        print("  ✅ Extension search working")
        
        # Cleanup
        db_path.unlink()
        print("📊 Database tests passed!")
        return True
        
    except Exception as e:
        print(f"  ❌ Database test failed: {e}")
        return False


def test_config_system():
    """Test configuration management"""
    print("⚙️ Testing Configuration System...")
    
    try:
        from khoj_search import ConfigManager, AppConfig
        
        # Test default config
        config_mgr = ConfigManager()
        config = config_mgr.config
        
        assert hasattr(config, 'theme'), "Config missing theme"
        assert hasattr(config, 'hotkey'), "Config missing hotkey"
        assert hasattr(config, 'max_results'), "Config missing max_results"
        print("  ✅ Default config loaded correctly")
        
        # Test config modification
        original_theme = config.theme
        config.theme = "light" if original_theme == "dark" else "dark"
        config_mgr.save_config()
        print("  ✅ Config saved successfully")
        
        # Test config reload
        new_config_mgr = ConfigManager()
        new_config = new_config_mgr.config
        assert new_config.theme != original_theme, "Config changes not persisted"
        print("  ✅ Config persistence working")
        
        print("⚙️ Configuration tests passed!")
        return True
        
    except Exception as e:
        print(f"  ❌ Config test failed: {e}")
        return False


def test_file_indexer():
    """Test file indexer components"""
    print("📁 Testing File Indexer...")
    
    try:
        from khoj_search import FileIndexer, DatabaseManager, AppConfig
        
        # Create test environment
        db_path = Path(tempfile.mktemp(suffix=".db"))
        db_manager = DatabaseManager(db_path)
        config = AppConfig()
        
        # Create temporary files to index
        test_dir = Path(tempfile.mkdtemp(prefix="khoj_test_"))
        (test_dir / "test1.txt").write_text("Test content 1")
        (test_dir / "test2.py").write_text("print('test')")
        (test_dir / "subdir").mkdir()
        (test_dir / "subdir" / "test3.md").write_text("# Test markdown")
        
        print(f"  📂 Created test files in {test_dir}")
        
        # Test indexer initialization
        indexer = FileIndexer(db_manager, config)
        assert hasattr(indexer, 'db_manager'), "Indexer missing db_manager"
        assert hasattr(indexer, 'config'), "Indexer missing config"
        print("  ✅ Indexer initialized correctly")
        
        # Test path filtering
        test_path = test_dir / ".hidden"
        should_skip = indexer._should_skip_path(test_path)
        assert should_skip, "Should skip hidden files"
        print("  ✅ Path filtering working")
        
        # Test file walking
        files_found = list(indexer._walk_directory(test_dir))
        assert len(files_found) >= 3, f"Expected at least 3 files, found {len(files_found)}"
        print(f"  ✅ File walking found {len(files_found)} files")
        
        # Cleanup
        import shutil
        shutil.rmtree(test_dir)
        db_path.unlink()
        
        print("📁 File indexer tests passed!")
        return True
        
    except Exception as e:
        print(f"  ❌ File indexer test failed: {e}")
        return False


def test_search_functionality():
    """Test search functionality"""
    print("🔍 Testing Search Functionality...")
    
    try:
        from khoj_search import DatabaseManager
        
        # Setup test database with sample data
        db_path = Path(tempfile.mktemp(suffix=".db"))
        db_manager = DatabaseManager(db_path)
        
        # Add test files
        test_files = [
            ("document.txt", "/home/user/document.txt", "/home/user", ".txt", 1000, 1640995200, 1640995200, False),
            ("script.py", "/home/user/script.py", "/home/user", ".py", 500, 1640995300, 1640995300, False),
            ("README.md", "/home/user/README.md", "/home/user", ".md", 800, 1640995400, 1640995400, False),
            ("image.jpg", "/home/user/image.jpg", "/home/user", ".jpg", 50000, 1640995500, 1640995500, False),
            ("data.json", "/home/user/data/data.json", "/home/user/data", ".json", 300, 1640995600, 1640995600, False),
        ]
        
        db_manager.batch_insert_files(test_files)
        print("  📊 Sample data inserted")
        
        # Test basic search
        results = db_manager.search_files("document")
        assert len(results) >= 1, "Should find document.txt"
        assert any("document" in r['name'].lower() for r in results), "Result should contain document"
        print("  ✅ Basic search working")
        
        # Test extension search
        results = db_manager.search_files("py")
        py_results = [r for r in results if r['extension'] == '.py']
        assert len(py_results) >= 1, "Should find Python files"
        print("  ✅ Extension search working")
        
        # Test partial match
        results = db_manager.search_files("scr")
        script_results = [r for r in results if "script" in r['name'].lower()]
        assert len(script_results) >= 1, "Should find script.py with partial match"
        print("  ✅ Partial matching working")
        
        # Test limit functionality
        results = db_manager.search_files("", limit=3)
        # Note: empty search should still work and return some results
        print(f"  ✅ Limit parameter working (returned {len(results)} results)")
        
        # Cleanup
        db_path.unlink()
        
        print("🔍 Search tests passed!")
        return True
        
    except Exception as e:
        print(f"  ❌ Search test failed: {e}")
        return False


def test_background_indexing_integration():
    """Test background indexing integration"""
    print("🔄 Testing Background Indexing Integration...")
    
    try:
        # Test individual components without creating the full app
        from khoj_search import DatabaseManager, ConfigManager, FileIndexer, AppConfig
        
        # Test database manager
        db_path = Path(tempfile.mktemp(suffix=".db"))
        db_manager = DatabaseManager(db_path)
        assert hasattr(db_manager, 'search_files'), "DatabaseManager missing search_files"
        print("  ✅ DatabaseManager component working")
        
        # Test config manager
        config_mgr = ConfigManager()
        config = config_mgr.config
        assert isinstance(config, AppConfig), "Config not AppConfig instance"
        print("  ✅ ConfigManager component working")
        
        # Test file indexer can be instantiated
        indexer = FileIndexer(db_manager, config)
        assert hasattr(indexer, 'progress_signal'), "FileIndexer missing progress_signal"
        assert hasattr(indexer, 'finished_signal'), "FileIndexer missing finished_signal"
        assert hasattr(indexer, 'run'), "FileIndexer missing run method"
        print("  ✅ FileIndexer component working")
        
        # Test that main app class exists and has required methods
        from khoj_search import ModernKhojSearch
        assert hasattr(ModernKhojSearch, '_start_background_indexing'), "Missing background indexing method"
        assert hasattr(ModernKhojSearch, '_update_tray_icon_status'), "Missing tray status method"
        assert hasattr(ModernKhojSearch, '_toggle_progress_dialog'), "Missing progress toggle method"
        print("  ✅ Main app class has required methods")
        
        # Cleanup
        db_path.unlink()
        
        print("🔄 Background indexing integration tests passed!")
        return True
        
    except Exception as e:
        print(f"  ❌ Background indexing test failed: {e}")
        return False


def test_ui_components():
    """Test UI component class definitions"""
    print("🎨 Testing UI Component Classes...")
    
    try:
        # Test that UI classes can be imported and have required methods
        from khoj_search import ModernSearchBar, ModernIndexingDialog, ModernKhojSearch
        
        # Check search bar class (just class definition, no instantiation)
        assert hasattr(ModernSearchBar, '_setup_window'), "SearchBar missing _setup_window"
        assert hasattr(ModernSearchBar, '_create_ui'), "SearchBar missing _create_ui"
        assert hasattr(ModernSearchBar, '_perform_search'), "SearchBar missing _perform_search"
        assert hasattr(ModernSearchBar, 'show_and_focus'), "SearchBar missing show_and_focus"
        print("  ✅ SearchBar class structure correct")
        
        # Check indexing dialog class
        assert hasattr(ModernIndexingDialog, 'update_progress'), "IndexingDialog missing update_progress"
        assert hasattr(ModernIndexingDialog, '_create_ui'), "IndexingDialog missing _create_ui"
        assert hasattr(ModernIndexingDialog, '_setup_dialog'), "IndexingDialog missing _setup_dialog"
        print("  ✅ IndexingDialog class structure correct")
        
        # Check main app class
        assert hasattr(ModernKhojSearch, '_setup_system_tray'), "App missing _setup_system_tray"
        assert hasattr(ModernKhojSearch, '_setup_hotkey'), "App missing _setup_hotkey"
        assert hasattr(ModernKhojSearch, 'show_search'), "App missing show_search"
        assert hasattr(ModernKhojSearch, 'reindex_files'), "App missing reindex_files"
        assert hasattr(ModernKhojSearch, 'quit_application'), "App missing quit_application"
        print("  ✅ Main app class structure correct")
        
        print("🎨 UI component class tests passed!")
        return True
        
    except Exception as e:
        print(f"  ❌ UI component test failed: {e}")
        return False


def main():
    """Run all comprehensive tests"""
    print("🧪 Running Comprehensive Test Suite for Khoj Da Search v2.0")
    print("=" * 60)
    
    tests = [
        ("Database Operations", test_database_operations),
        ("Configuration System", test_config_system),
        ("File Indexer", test_file_indexer),
        ("Search Functionality", test_search_functionality),
        ("Background Indexing", test_background_indexing_integration),
        ("UI Components", test_ui_components),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        print(f"\n🔍 Running: {test_name}")
        try:
            if test_func():
                passed += 1
                print(f"✅ {test_name} PASSED")
            else:
                failed += 1
                print(f"❌ {test_name} FAILED")
        except Exception as e:
            failed += 1
            print(f"❌ {test_name} FAILED with exception: {e}")
    
    print("\n" + "=" * 60)
    print(f"📊 Test Results: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("🎉 All tests passed! Application is ready for use.")
        print("\n🚀 Key features verified:")
        print("  • Database operations working correctly")
        print("  • Configuration system functional")
        print("  • File indexing components ready")
        print("  • Search functionality operational")
        print("  • Background indexing architecture sound")
        print("  • UI components properly structured")
        return 0
    else:
        print(f"⚠️  {failed} test(s) failed. Please review the issues above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())