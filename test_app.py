#!/usr/bin/env python3
"""
Test script for the modernized Khoj Da Search application
"""

import sys
import tempfile
import shutil
from pathlib import Path
import sqlite3

def create_test_files():
    """Create some test files for indexing"""
    test_dir = Path(tempfile.mkdtemp(prefix="khoj_test_"))
    
    # Create test files
    (test_dir / "document.txt").write_text("This is a test document")
    (test_dir / "script.py").write_text("print('Hello World')")
    (test_dir / "data.json").write_text('{"test": true}')
    (test_dir / "readme.md").write_text("# Test Project")
    
    # Create subdirectory
    subdir = test_dir / "subdir"
    subdir.mkdir()
    (subdir / "nested.txt").write_text("Nested file content")
    
    return test_dir

def test_database_operations():
    """Test database operations"""
    from khoj_search import DatabaseManager
    
    # Create temporary database
    db_path = Path(tempfile.mktemp(suffix=".db"))
    db_manager = DatabaseManager(db_path)
    
    # Test batch insert
    test_files = [
        ("test.txt", "/tmp/test.txt", "/tmp", ".txt", 100, 1640995200, 1640995200, False),
        ("script.py", "/tmp/script.py", "/tmp", ".py", 200, 1640995300, 1640995300, False),
    ]
    
    result = db_manager.batch_insert_files(test_files)
    print(f"✅ Inserted {result} files")
    
    # Test search
    results = db_manager.search_files("test")
    print(f"✅ Search found {len(results)} results")
    
    # Test file count
    count = db_manager.get_file_count()
    print(f"✅ Total files in database: {count}")
    
    # Cleanup
    db_path.unlink()
    
    return True

def test_config_manager():
    """Test configuration management"""
    from khoj_search import ConfigManager, AppConfig
    
    config_manager = ConfigManager()
    config = config_manager.config
    
    print(f"✅ Config loaded - Theme: {config.theme}, Hotkey: {config.hotkey}")
    
    # Test config modification
    config.theme = "light"
    config_manager.save_config()
    print("✅ Configuration saved successfully")
    
    return True

def main():
    """Run basic tests"""
    print("🧪 Testing Khoj Da Search Components...")
    
    try:
        # Test database operations
        print("\n📊 Testing Database Operations...")
        test_database_operations()
        
        # Test configuration
        print("\n⚙️ Testing Configuration Management...")
        test_config_manager()
        
        # Create test files for manual testing
        print("\n📁 Creating Test Files...")
        test_dir = create_test_files()
        print(f"✅ Test files created in: {test_dir}")
        print("   You can now run the main application to test indexing these files")
        
        print("\n🎉 All tests passed!")
        print(f"\nTo run the application:")
        print(f"  python khoj_search.py")
        print(f"\nTo cleanup test files:")
        print(f"  rm -rf {test_dir}")
        
        return 0
        
    except ImportError as e:
        print(f"❌ Missing dependencies: {e}")
        print("Please install required packages: pip install -r requirements.txt")
        return 1
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())