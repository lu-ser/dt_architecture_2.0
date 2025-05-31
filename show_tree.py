#!/usr/bin/env python3
"""
Project tree viewer script.

Shows the complete directory structure of the project in a tree format.
"""

import os
from pathlib import Path


def show_tree(directory=None, prefix="", max_depth=None, current_depth=0, 
              exclude_dirs=None, exclude_files=None, show_hidden=False):
    """
    Display directory tree structure.
    
    Args:
        directory: Directory to scan (default: current directory)
        prefix: Prefix for current level (used for recursion)
        max_depth: Maximum depth to scan (None for unlimited)
        current_depth: Current depth level (used for recursion)
        exclude_dirs: List of directory names to exclude
        exclude_files: List of file patterns to exclude
        show_hidden: Whether to show hidden files/directories
    """
    if directory is None:
        directory = Path.cwd()
    else:
        directory = Path(directory)
    
    if exclude_dirs is None:
        exclude_dirs = {'.git', '__pycache__', '.pytest_cache', 'node_modules', 
                       '.vscode', '.idea', 'htmlcov', '.tox', '.coverage'}
    
    if exclude_files is None:
        exclude_files = {'.pyc', '.pyo', '.pyd', '.so', '.egg-info', 
                        '.DS_Store', 'Thumbs.db', '.gitignore'}
    
    # Check depth limit
    if max_depth is not None and current_depth >= max_depth:
        return
    
    try:
        # Get all items in directory
        items = list(directory.iterdir())
        # Filter out excluded items
        if not show_hidden:
            items = [item for item in items if not item.name.startswith('.')]
        
        # Separate directories and files
        dirs = []
        files = []
        
        for item in items:
            if item.is_dir():
                if item.name not in exclude_dirs:
                    dirs.append(item)
            else:
                # Check if file should be excluded
                should_exclude = False
                for exclude_pattern in exclude_files:
                    if item.name.endswith(exclude_pattern) or item.name == exclude_pattern:
                        should_exclude = True
                        break
                if not should_exclude:
                    files.append(item)
        
        # Sort directories and files
        dirs.sort(key=lambda x: x.name.lower())
        files.sort(key=lambda x: x.name.lower())
        
        # Combine directories first, then files
        all_items = dirs + files
        
        # Display items
        for i, item in enumerate(all_items):
            is_last = i == len(all_items) - 1
            
            # Choose the appropriate tree characters
            if is_last:
                current_prefix = prefix + "└── "
                next_prefix = prefix + "    "
            else:
                current_prefix = prefix + "├── "
                next_prefix = prefix + "│   "
            
            # Display item name with appropriate icon
            if item.is_dir():
                print(f"{current_prefix}📁 {item.name}/")
                # Recursively show subdirectory
                show_tree(item, next_prefix, max_depth, current_depth + 1, 
                         exclude_dirs, exclude_files, show_hidden)
            else:
                # Choose icon based on file type
                icon = get_file_icon(item.name)
                print(f"{current_prefix}{icon} {item.name}")
    
    except PermissionError:
        print(f"{prefix}❌ Permission denied")
    except Exception as e:
        print(f"{prefix}❌ Error: {e}")


def get_file_icon(filename):
    """Get appropriate icon for file type."""
    name_lower = filename.lower()
    
    # Python files
    if name_lower.endswith('.py'):
        return "🐍"
    
    # Configuration files
    elif name_lower.endswith(('.json', '.yaml', '.yml', '.toml', '.ini', '.cfg')):
        return "⚙️"
    
    # Documentation
    elif name_lower.endswith(('.md', '.rst', '.txt', '.doc', '.docx')):
        return "📄"
    
    # Requirements/dependencies
    elif 'requirements' in name_lower or name_lower in ('pipfile', 'poetry.lock', 'package.json'):
        return "📦"
    
    # Docker files
    elif name_lower.startswith('dockerfile') or name_lower == 'docker-compose.yml':
        return "🐳"
    
    # Test files
    elif name_lower.startswith('test_') or name_lower.endswith('_test.py'):
        return "🧪"
    
    # Script files
    elif name_lower.endswith(('.sh', '.bat', '.cmd')):
        return "📜"
    
    # Web files
    elif name_lower.endswith(('.html', '.css', '.js', '.jsx', '.ts', '.tsx')):
        return "🌐"
    
    # Image files
    elif name_lower.endswith(('.jpg', '.jpeg', '.png', '.gif', '.svg', '.ico')):
        return "🖼️"
    
    # Archive files
    elif name_lower.endswith(('.zip', '.tar', '.gz', '.rar', '.7z')):
        return "📦"
    
    # License files
    elif 'license' in name_lower or 'licence' in name_lower:
        return "📜"
    
    # Default file
    else:
        return "📄"


def print_project_info():
    """Print project information."""
    cwd = Path.cwd()
    print(f"📍 Project root: {cwd}")
    print(f"📊 Scanning from: {cwd.name}")
    print("=" * 60)


def main():
    """Main function."""
    print("🌳 Digital Twin Platform - Project Tree")
    print_project_info()
    
    # Show basic tree
    show_tree()
    
    print("\n" + "=" * 60)
    
    # Count some statistics
    total_py_files = 0
    total_test_files = 0
    total_dirs = 0
    
    for root, dirs, files in os.walk('.'):
        # Exclude common unwanted directories
        dirs[:] = [d for d in dirs if d not in {'.git', '__pycache__', '.pytest_cache', 'node_modules', '.vscode', '.idea', 'htmlcov', '.tox'}]
        
        total_dirs += len(dirs)
        
        for file in files:
            if file.endswith('.py'):
                total_py_files += 1
                if file.startswith('test_') or file.endswith('_test.py'):
                    total_test_files += 1
    
    print(f"📊 Project Statistics:")
    print(f"   • 📁 Directories: {total_dirs}")
    print(f"   • 🐍 Python files: {total_py_files}")
    print(f"   • 🧪 Test files: {total_test_files}")
    
    # Check for key files
    key_files = [
        'requirements.txt',
        'setup.py',
        'pyproject.toml',
        'README.md',
        'LICENSE'
    ]
    
    found_key_files = []
    for key_file in key_files:
        if Path(key_file).exists():
            found_key_files.append(key_file)
    
    if found_key_files:
        print(f"   • 📋 Key files found: {', '.join(found_key_files)}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⏹️ Interrupted by user")
    except Exception as e:
        print(f"\n💥 Error: {e}")