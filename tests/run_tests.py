#!/usr/bin/env python3
"""
Test runner for the Digital Twin Platform.

This script runs all tests and provides detailed output about the test results.
It can be used for continuous integration and development testing.
"""

import sys
import os
import subprocess
import argparse
from pathlib import Path
import time


def setup_python_path():
    """Setup Python path to include src directory."""
    # Get the project root directory - handle both cases: run from root or from tests
    script_dir = Path(__file__).parent
    if script_dir.name == 'tests':
        # Script is in tests/ directory
        project_root = script_dir.parent
    else:
        # Script is in root directory
        project_root = script_dir
    
    src_path = project_root / "src"
    
    # Add src to Python path
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
    
    # Also set PYTHONPATH environment variable
    current_pythonpath = os.environ.get('PYTHONPATH', '')
    if str(src_path) not in current_pythonpath:
        if current_pythonpath:
            os.environ['PYTHONPATH'] = f"{src_path}:{current_pythonpath}"
        else:
            os.environ['PYTHONPATH'] = str(src_path)
    
    return project_root


def check_dependencies():
    """Check if required dependencies are installed."""
    # Check pytest
    try:
        import pytest
        print(f"✅ pytest version: {pytest.__version__}")
    except ImportError:
        print("❌ pytest not installed. Install with: pip install pytest")
        return False
    
    # Check pytest-asyncio (optional)
    asyncio_mode = None
    try:
        import pytest_asyncio
        print(f"✅ pytest-asyncio version: {pytest_asyncio.__version__}")
        # Check if asyncio-mode is supported
        if hasattr(pytest_asyncio, '__version__'):
            version = pytest_asyncio.__version__
            major, minor = map(int, version.split('.')[:2])
            if major > 0 or minor >= 21:
                asyncio_mode = "auto"
            else:
                asyncio_mode = "legacy"
    except ImportError:
        print("⚠️  pytest-asyncio not installed. Async tests may not work properly.")
        print("    Install with: pip install pytest-asyncio")
        asyncio_mode = None
    
    return True, asyncio_mode


def run_tests(test_pattern=None, verbose=False, coverage=False, output_format='text'):
    """
    Run tests with specified options.
    
    Args:
        test_pattern: Pattern to filter tests
        verbose: Whether to run tests in verbose mode
        coverage: Whether to generate coverage report
        output_format: Output format ('text', 'xml', 'json')
    
    Returns:
        Test result code (0 for success, non-zero for failure)
    """
    # Setup Python path and get project root
    project_root = setup_python_path()
    
    # Check dependencies
    deps_result = check_dependencies()
    if isinstance(deps_result, tuple):
        deps_ok, asyncio_mode = deps_result
    else:
        deps_ok = deps_result
        asyncio_mode = None
    
    if not deps_ok:
        return 1
    
    # Build pytest command
    cmd = ['python', '-m', 'pytest']
    
    # Add test directory
    tests_dir = project_root / 'tests'
    
    # Check if tests directory exists
    if not tests_dir.exists():
        print(f"❌ Tests directory not found: {tests_dir}")
        return 1
    
    cmd.append(str(tests_dir))
    
    # Add options
    if verbose:
        cmd.extend(['-v', '-s'])
    
    if test_pattern:
        cmd.extend(['-k', test_pattern])
    
    # Add async support if available
    if asyncio_mode:
        if asyncio_mode == "auto":
            cmd.append('--asyncio-mode=auto')
        elif asyncio_mode == "legacy":
            # For older versions, just add pytest-asyncio
            pass
    
    # Add coverage if requested
    if coverage:
        try:
            import pytest_cov
            cmd.extend(['--cov=src', '--cov-report=html', '--cov-report=term'])
        except ImportError:
            print("⚠️  pytest-cov not installed. Skipping coverage.")
    
    # Add output format options
    if output_format == 'xml':
        cmd.extend(['--junitxml=test-results.xml'])
    elif output_format == 'json':
        try:
            import pytest_json_report
            cmd.extend(['--json-report', '--json-report-file=test-results.json'])
        except ImportError:
            print("⚠️  pytest-json-report not installed. Using text output.")
    
    print(f"🧪 Running tests with command: {' '.join(cmd)}")
    print("=" * 80)
    
    # Run tests
    start_time = time.time()
    result = subprocess.run(cmd, cwd=project_root)
    end_time = time.time()
    
    print("=" * 80)
    print(f"⏱️  Tests completed in {end_time - start_time:.2f} seconds")
    
    if result.returncode == 0:
        print("✅ All tests passed!")
    else:
        print("❌ Some tests failed!")
    
    return result.returncode


def run_specific_test_file(test_file, verbose=False):
    """
    Run a specific test file.
    
    Args:
        test_file: Path to the test file
        verbose: Whether to run in verbose mode
    
    Returns:
        Test result code
    """
    project_root = setup_python_path()
    
    deps_result = check_dependencies()
    if isinstance(deps_result, tuple):
        deps_ok, asyncio_mode = deps_result
    else:
        deps_ok = deps_result
        asyncio_mode = None
    
    if not deps_ok:
        return 1
    
    cmd = ['python', '-m', 'pytest', test_file]
    
    # Add async support if available
    if asyncio_mode == "auto":
        cmd.append('--asyncio-mode=auto')
    
    if verbose:
        cmd.extend(['-v', '-s'])
    
    print(f"🧪 Running test file: {test_file}")
    print("=" * 80)
    
    start_time = time.time()
    result = subprocess.run(cmd, cwd=project_root)
    end_time = time.time()
    
    print("=" * 80)
    print(f"⏱️  Test file completed in {end_time - start_time:.2f} seconds")
    
    return result.returncode


def list_available_tests():
    """List all available test files."""
    project_root = setup_python_path()
    tests_dir = project_root / 'tests'
    
    if not tests_dir.exists():
        print("❌ Tests directory not found!")
        return
    
    print("📋 Available test files:")
    print("=" * 40)
    
    test_files = list(tests_dir.glob('test_*.py'))
    
    if not test_files:
        print("No test files found!")
        return
    
    for test_file in sorted(test_files):
        print(f"  • {test_file.name}")
    
    print(f"\nTotal: {len(test_files)} test files")
    print(f"Tests directory: {tests_dir}")


def create_test_environment():
    """Create necessary directories and files for testing."""
    project_root = setup_python_path()
    
    # Create directories if they don't exist
    directories = [
        'tests',
        'tests/mocks',
        'src',
        'src/core',
        'src/core/interfaces',
        'src/core/registry',
        'src/utils',
        'logs',
        'data'
    ]
    
    created_dirs = []
    for directory in directories:
        dir_path = project_root / directory
        if not dir_path.exists():
            dir_path.mkdir(parents=True, exist_ok=True)
            created_dirs.append(directory)
    
    # Create __init__.py files for Python packages
    init_files = [
        'tests/__init__.py',
        'tests/mocks/__init__.py',
        'src/__init__.py',
        'src/core/__init__.py',
        'src/core/interfaces/__init__.py',
        'src/core/registry/__init__.py',
        'src/utils/__init__.py'
    ]
    
    created_files = []
    for init_file in init_files:
        file_path = project_root / init_file
        if not file_path.exists():
            file_path.write_text('"""Package initialization."""\n')
            created_files.append(init_file)
    
    if created_dirs:
        print(f"✅ Created {len(created_dirs)} directories")
    if created_files:
        print(f"✅ Created {len(created_files)} __init__.py files")
    
    print("✅ Test environment setup complete!")


def main():
    """Main function to handle command line arguments and run tests."""
    parser = argparse.ArgumentParser(
        description='Test runner for Digital Twin Platform',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_tests.py                           # Run all tests
  python run_tests.py -v                        # Run with verbose output
  python run_tests.py -k "test_exceptions"      # Run tests matching pattern
  python run_tests.py --coverage                # Run with coverage report
  python run_tests.py --file tests/test_config.py  # Run specific test file
  python run_tests.py --list                    # List available tests
  python run_tests.py --setup                   # Setup test environment
        """
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Run tests in verbose mode'
    )
    
    parser.add_argument(
        '-k', '--pattern',
        help='Run tests matching the given pattern'
    )
    
    parser.add_argument(
        '--coverage',
        action='store_true',
        help='Generate coverage report'
    )
    
    parser.add_argument(
        '--format',
        choices=['text', 'xml', 'json'],
        default='text',
        help='Output format for test results'
    )
    
    parser.add_argument(
        '--file',
        help='Run a specific test file'
    )
    
    parser.add_argument(
        '--list',
        action='store_true',
        help='List available test files'
    )
    
    parser.add_argument(
        '--setup',
        action='store_true',
        help='Setup test environment (create directories and __init__.py files)'
    )
    
    args = parser.parse_args()
    
    # Handle specific commands
    if args.setup:
        create_test_environment()
        return 0
    
    if args.list:
        list_available_tests()
        return 0
    
    if args.file:
        return run_specific_test_file(args.file, args.verbose)
    
    # Run tests
    return run_tests(
        test_pattern=args.pattern,
        verbose=args.verbose,
        coverage=args.coverage,
        output_format=args.format
    )


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)