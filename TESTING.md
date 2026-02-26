# Testing Guide

## Test Types

### 1. Standalone Test Scripts (Existing)
These are the original test files that run independently:

```bash
# Run all legacy tests
python run_all_tests.py

# Run specific test files
python test_normalization.py
python test_edge_cases.py
python test_supplier_matching.py
python test_comprehensive.py
python test_security_shipping.py
```

**Note:** `test_security_shipping.py` was fixed to not conflict with pytest (renamed `test()` helper to `assert_test()`).

### 2. Pytest Tests (New)
Modern pytest-style tests in the `tests/` directory:

```bash
# Run all pytest tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_example.py

# Run tests matching a pattern
pytest -k test_database

# Run tests with a specific marker
pytest -m unit
pytest -m integration
```

## Pytest Configuration

Configuration is in `pytest.ini`:
- Test discovery pattern: `test_*.py` or `pytest_*.py`
- Test directory: `tests/`
- Markers: `unit`, `integration`, `api`, `security`, `slow`

## Writing Pytest Tests

Example test structure:

```python
import pytest
from database import get_db

@pytest.mark.unit
def test_something():
    """Test description."""
    # Arrange
    expected = True

    # Act
    result = some_function()

    # Assert
    assert result == expected
```

## Test Markers

Use markers to categorize tests:

- `@pytest.mark.unit` - Fast unit tests
- `@pytest.mark.integration` - Tests requiring database
- `@pytest.mark.api` - API endpoint tests
- `@pytest.mark.security` - Security-related tests
- `@pytest.mark.slow` - Long-running tests

Run specific categories:
```bash
pytest -m "unit"
pytest -m "not slow"
pytest -m "unit or integration"
```

## Coverage Reports

Run tests with coverage:
```bash
pytest --cov=. --cov-report=html
pytest --cov=routes --cov-report=term-missing
```

## Current Test Status

**Standalone Tests:** ✅ All passing (77/77 tests in comprehensive suite)
**Pytest Tests:** ✅ 55 tests passing (100% pass rate)

### Pytest Test Coverage

New features added have comprehensive pytest coverage:

- **test_example.py** (4 tests) - Database schema validation
- **test_email_filtering.py** (7 tests) - Email date filtering for Gmail/Outlook
- **test_exports.py** (10 tests) - PDF/Excel/CSV export with date range filtering
- **test_invoice_voucher.py** (9 tests) - Invoice voucher print view functionality
- **test_void_system.py** (11 tests) - TF gap prevention via void system
- **test_receipt_upload.py** (14 tests) - Fiscal receipt upload, validation, and security

All new features are fully tested and working correctly!

## Migration Path

The legacy test scripts will continue to work. New tests should be written as pytest tests in the `tests/` directory for better:
- Test discovery
- Fixtures and reusability
- Parallel execution
- IDE integration
- Coverage reporting
