import os
import shutil
import ast
from pathlib import Path

class DocstringRemoverBackup:

    def __init__(self, source_dir, backup_dir, excluded_dirs=None):
        self.source_dir = Path(source_dir)
        self.backup_dir = Path(backup_dir)
        self.excluded_dirs = excluded_dirs or ['.venv', '__pycache__', '.git']

    def create_backup(self):
        if not self.source_dir.exists():
            raise FileNotFoundError(f'Source directory does not exist: {self.source_dir}')
        for root, dirs, files in os.walk(self.source_dir):
            dirs[:] = [d for d in dirs if d not in self.excluded_dirs]
            relative_root = Path(root).relative_to(self.source_dir)
            backup_root = self.backup_dir / relative_root
            backup_root.mkdir(parents=True, exist_ok=True)
            for file in files:
                source_file = Path(root) / file
                backup_file = backup_root / file
                shutil.copy2(source_file, backup_file)

    def remove_docstrings(self, source_code):
        try:
            tree = ast.parse(source_code)
            if not hasattr(tree, 'body') or not tree.body:
                return source_code
            if isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, (ast.Constant, ast.Str)) and isinstance(tree.body[0].value.s if hasattr(tree.body[0].value, 's') else tree.body[0].value.value, str):
                tree.body.pop(0)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, (ast.Constant, ast.Str)) and isinstance(node.body[0].value.s if hasattr(node.body[0].value, 's') else node.body[0].value.value, str):
                        node.body.pop(0)
            return ast.unparse(tree)
        except Exception as e:
            print(f'Error while removing docstrings: {e}')
            return source_code

    def process_python_files_in_backup(self):
        for root, dirs, files in os.walk(self.backup_dir):
            dirs[:] = [d for d in dirs if d not in self.excluded_dirs]
            for file in files:
                if file.endswith('.py'):
                    backup_file = Path(root) / file
                    try:
                        with open(backup_file, 'r', encoding='utf-8') as f:
                            code = f.read()
                        if not code.strip():
                            continue
                        processed_code = self.remove_docstrings(code)
                        with open(backup_file, 'w', encoding='utf-8') as f:
                            f.write(processed_code)
                    except Exception as e:
                        print(f'Error processing {backup_file}: {e}')

    def run(self):
        print('Creating backup...')
        self.create_backup()
        print('Backup created successfully.')
        print('Processing Python files in the backup...')
        self.process_python_files_in_backup()
        print('Processing complete. Docstrings removed in backup files.')
if __name__ == '__main__':
    source_directory = './'
    backup_directory = './backup_directory'
    remover = DocstringRemoverBackup(source_directory, backup_directory)
    remover.run()