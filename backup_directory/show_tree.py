import os
from pathlib import Path

def show_tree(directory=None, prefix='', max_depth=None, current_depth=0, exclude_dirs=None, exclude_files=None, show_hidden=False):
    if directory is None:
        directory = Path.cwd()
    else:
        directory = Path(directory)
    if exclude_dirs is None:
        exclude_dirs = {'.git', '__pycache__', '.pytest_cache', 'node_modules', '.vscode', '.idea', 'htmlcov', '.tox', '.coverage'}
    if exclude_files is None:
        exclude_files = {'.pyc', '.pyo', '.pyd', '.so', '.egg-info', '.DS_Store', 'Thumbs.db', '.gitignore'}
    if max_depth is not None and current_depth >= max_depth:
        return
    try:
        items = list(directory.iterdir())
        if not show_hidden:
            items = [item for item in items if not item.name.startswith('.')]
        dirs = []
        files = []
        for item in items:
            if item.is_dir():
                if item.name not in exclude_dirs:
                    dirs.append(item)
            else:
                should_exclude = False
                for exclude_pattern in exclude_files:
                    if item.name.endswith(exclude_pattern) or item.name == exclude_pattern:
                        should_exclude = True
                        break
                if not should_exclude:
                    files.append(item)
        dirs.sort(key=lambda x: x.name.lower())
        files.sort(key=lambda x: x.name.lower())
        all_items = dirs + files
        for i, item in enumerate(all_items):
            is_last = i == len(all_items) - 1
            if is_last:
                current_prefix = prefix + '└── '
                next_prefix = prefix + '    '
            else:
                current_prefix = prefix + '├── '
                next_prefix = prefix + '│   '
            if item.is_dir():
                print(f'{current_prefix}📁 {item.name}/')
                show_tree(item, next_prefix, max_depth, current_depth + 1, exclude_dirs, exclude_files, show_hidden)
            else:
                icon = get_file_icon(item.name)
                print(f'{current_prefix}{icon} {item.name}')
    except PermissionError:
        print(f'{prefix}❌ Permission denied')
    except Exception as e:
        print(f'{prefix}❌ Error: {e}')

def get_file_icon(filename):
    name_lower = filename.lower()
    if name_lower.endswith('.py'):
        return '🐍'
    elif name_lower.endswith(('.json', '.yaml', '.yml', '.toml', '.ini', '.cfg')):
        return '⚙️'
    elif name_lower.endswith(('.md', '.rst', '.txt', '.doc', '.docx')):
        return '📄'
    elif 'requirements' in name_lower or name_lower in ('pipfile', 'poetry.lock', 'package.json'):
        return '📦'
    elif name_lower.startswith('dockerfile') or name_lower == 'docker-compose.yml':
        return '🐳'
    elif name_lower.startswith('test_') or name_lower.endswith('_test.py'):
        return '🧪'
    elif name_lower.endswith(('.sh', '.bat', '.cmd')):
        return '📜'
    elif name_lower.endswith(('.html', '.css', '.js', '.jsx', '.ts', '.tsx')):
        return '🌐'
    elif name_lower.endswith(('.jpg', '.jpeg', '.png', '.gif', '.svg', '.ico')):
        return '🖼️'
    elif name_lower.endswith(('.zip', '.tar', '.gz', '.rar', '.7z')):
        return '📦'
    elif 'license' in name_lower or 'licence' in name_lower:
        return '📜'
    else:
        return '📄'

def print_project_info():
    cwd = Path.cwd()
    print(f'📍 Project root: {cwd}')
    print(f'📊 Scanning from: {cwd.name}')
    print('=' * 60)

def main():
    print('🌳 Digital Twin Platform - Project Tree')
    print_project_info()
    show_tree()
    print('\n' + '=' * 60)
    total_py_files = 0
    total_test_files = 0
    total_dirs = 0
    for root, dirs, files in os.walk('.'):
        dirs[:] = [d for d in dirs if d not in {'.git', '__pycache__', '.pytest_cache', 'node_modules', '.vscode', '.idea', 'htmlcov', '.tox'}]
        total_dirs += len(dirs)
        for file in files:
            if file.endswith('.py'):
                total_py_files += 1
                if file.startswith('test_') or file.endswith('_test.py'):
                    total_test_files += 1
    print(f'📊 Project Statistics:')
    print(f'   • 📁 Directories: {total_dirs}')
    print(f'   • 🐍 Python files: {total_py_files}')
    print(f'   • 🧪 Test files: {total_test_files}')
    key_files = ['requirements.txt', 'setup.py', 'pyproject.toml', 'README.md', 'LICENSE']
    found_key_files = []
    for key_file in key_files:
        if Path(key_file).exists():
            found_key_files.append(key_file)
    if found_key_files:
        print(f"   • 📋 Key files found: {', '.join(found_key_files)}")
if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n\n⏹️ Interrupted by user')
    except Exception as e:
        print(f'\n💥 Error: {e}')