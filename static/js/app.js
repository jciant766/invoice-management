/**
 * Invoice Management System - Frontend JavaScript
 * Kunsill Lokali Tas-Sliema
 */

// Toast notification system
function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);

    setTimeout(() => {
        toast.remove();
    }, 3000);
}

// Format currency
function formatCurrency(amount) {
    return new Intl.NumberFormat('mt-MT', {
        style: 'currency',
        currency: 'EUR'
    }).format(amount);
}

// Format date to DD/MM/YYYY
function formatDate(dateString) {
    if (!dateString) return '';
    const date = new Date(dateString);
    return date.toLocaleDateString('mt-MT', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric'
    });
}

// Confirm before form submission
function confirmSubmit(message) {
    return confirm(message || 'Are you sure you want to submit?');
}

// Auto-save form data to localStorage
function enableAutoSave(formId) {
    const form = document.getElementById(formId);
    if (!form) return;

    const storageKey = `autosave_${formId}`;

    // Load saved data
    const savedData = localStorage.getItem(storageKey);
    if (savedData) {
        try {
            const data = JSON.parse(savedData);
            Object.keys(data).forEach(key => {
                const field = form.elements[key];
                if (field && field.type !== 'checkbox') {
                    field.value = data[key];
                }
            });
        } catch (e) {
            console.error('Error loading autosave data:', e);
        }
    }

    // Save on change
    form.addEventListener('change', () => {
        const formData = new FormData(form);
        const data = {};
        formData.forEach((value, key) => {
            data[key] = value;
        });
        localStorage.setItem(storageKey, JSON.stringify(data));
    });

    // Clear on successful submit
    form.addEventListener('submit', () => {
        localStorage.removeItem(storageKey);
    });
}

// Keyboard navigation for tables
function enableTableKeyboardNav(tableId) {
    const table = document.getElementById(tableId);
    if (!table) return;

    const rows = table.querySelectorAll('tbody tr');
    let currentRow = 0;

    document.addEventListener('keydown', (e) => {
        if (document.activeElement.tagName === 'INPUT' ||
            document.activeElement.tagName === 'SELECT' ||
            document.activeElement.tagName === 'TEXTAREA') {
            return;
        }

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            currentRow = Math.min(currentRow + 1, rows.length - 1);
            rows[currentRow].scrollIntoView({ behavior: 'smooth', block: 'center' });
            rows[currentRow].classList.add('bg-blue-50');
            if (currentRow > 0) rows[currentRow - 1].classList.remove('bg-blue-50');
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            currentRow = Math.max(currentRow - 1, 0);
            rows[currentRow].scrollIntoView({ behavior: 'smooth', block: 'center' });
            rows[currentRow].classList.add('bg-blue-50');
            if (currentRow < rows.length - 1) rows[currentRow + 1].classList.remove('bg-blue-50');
        } else if (e.key === 'Enter') {
            const editLink = rows[currentRow].querySelector('a[href*="edit"]');
            if (editLink) {
                editLink.click();
            }
        }
    });
}

// Debounce function for search/filter
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Search filter for tables
function enableTableSearch(inputId, tableId) {
    const input = document.getElementById(inputId);
    const table = document.getElementById(tableId);
    if (!input || !table) return;

    const search = debounce((query) => {
        const rows = table.querySelectorAll('tbody tr');
        const lowerQuery = query.toLowerCase();

        rows.forEach(row => {
            const text = row.textContent.toLowerCase();
            row.style.display = text.includes(lowerQuery) ? '' : 'none';
        });
    }, 300);

    input.addEventListener('input', (e) => {
        search(e.target.value);
    });
}

// Export table to CSV
function exportTableToCSV(tableId, filename = 'export.csv') {
    const table = document.getElementById(tableId);
    if (!table) return;

    const rows = table.querySelectorAll('tr');
    const csv = [];

    rows.forEach(row => {
        const cols = row.querySelectorAll('td, th');
        const rowData = [];
        cols.forEach(col => {
            // Clean the text
            let text = col.textContent.replace(/"/g, '""').trim();
            // Remove action buttons column
            if (!col.querySelector('button') && !col.querySelector('a')) {
                rowData.push(`"${text}"`);
            }
        });
        if (rowData.length > 0) {
            csv.push(rowData.join(','));
        }
    });

    const csvContent = csv.join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.click();
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    // Add loading state to forms
    document.querySelectorAll('form').forEach(form => {
        form.addEventListener('submit', function() {
            const submitBtn = this.querySelector('button[type="submit"]');
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.innerHTML = '<span class="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full mr-2"></span>Processing...';
            }
        });
    });

    // Auto-focus first input in forms
    const firstInput = document.querySelector('form input:not([type="hidden"]):not([type="checkbox"])');
    if (firstInput) {
        firstInput.focus();
    }

    // Add tooltips
    document.querySelectorAll('[title]').forEach(el => {
        el.classList.add('cursor-help');
    });

    console.log('Invoice Management System loaded');
});

// Utility: Copy text to clipboard
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        showToast('Copied to clipboard!');
    }).catch(err => {
        console.error('Failed to copy:', err);
    });
}

// Utility: Print current page
function printPage() {
    window.print();
}
