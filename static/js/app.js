/**
 * Invoice Management System - Frontend JavaScript
 * Kunsill Lokali Tas-Sliema
 */

// ========================================
// ERROR HANDLING SYSTEM
// ========================================
// This replaces ugly Chrome error pages with nice user-friendly messages

/**
 * Handle API errors from the backend
 * Automatically detects error format and displays appropriately
 *
 * Usage:
 *   const response = await fetch('/email/parse/123');
 *   if (!response.ok) {
 *       handleApiError(response);
 *       return;
 *   }
 */
async function handleApiError(response) {
    try {
        const error = await response.json();

        // Check if it's our standardized error format
        if (error.error && error.error.message) {
            showErrorModal({
                title: getErrorTitle(error.error.type),
                message: error.error.message,
                details: error.error.details,
                action: error.error.user_action
            });
        } else if (error.error) {
            // Fallback for old error format
            showToast(error.error, 'error');
        } else {
            // Generic error
            showToast('An error occurred. Please try again.', 'error');
        }
    } catch (e) {
        // If we can't parse the error response, show generic message
        showToast(`Error: ${response.status} - ${response.statusText}`, 'error');
    }
}

/**
 * Get a friendly error title based on error type
 */
function getErrorTitle(errorType) {
    const titles = {
        'validation_error': 'Validation Error',
        'ai_parsing_error': 'Unable to Parse Email',
        'database_error': 'Database Error',
        'email_service_error': 'Email Service Error',
        'not_found': 'Not Found',
        'internal_error': 'Server Error',
        'http_error': 'Request Error'
    };
    return titles[errorType] || 'Error';
}

/**
 * Show detailed error modal
 * This is better than a toast for errors with detailed info
 */
function showErrorModal({title, message, details = {}, action = null}) {
    // Remove existing error modal if any
    const existing = document.getElementById('errorModal');
    if (existing) existing.remove();

    const modal = document.createElement('div');
    modal.id = 'errorModal';
    modal.className = 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50';
    modal.innerHTML = `
        <div class="bg-white rounded-lg shadow-xl max-w-md w-full mx-4 p-6">
            <!-- Error Icon -->
            <div class="flex items-center justify-center w-12 h-12 mx-auto bg-red-100 rounded-full mb-4">
                <svg class="w-6 h-6 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                </svg>
            </div>

            <!-- Error Title -->
            <h3 class="text-lg font-bold text-gray-900 text-center mb-2">${title}</h3>

            <!-- Error Message -->
            <p class="text-gray-700 text-center mb-4">${message}</p>

            <!-- User Action (what to do) -->
            ${action ? `
                <div class="bg-blue-50 border-l-4 border-blue-400 p-3 mb-4">
                    <p class="text-sm text-blue-700">
                        <strong>What to do:</strong> ${action}
                    </p>
                </div>
            ` : ''}

            <!-- Details (for debugging) -->
            ${Object.keys(details).length > 0 ? `
                <details class="mb-4">
                    <summary class="text-sm text-gray-500 cursor-pointer hover:text-gray-700">
                        Show technical details
                    </summary>
                    <pre class="text-xs bg-gray-100 p-2 rounded mt-2 overflow-auto">${JSON.stringify(details, null, 2)}</pre>
                </details>
            ` : ''}

            <!-- Close Button -->
            <button onclick="document.getElementById('errorModal').remove()"
                    class="w-full bg-red-600 text-white px-4 py-2 rounded-lg hover:bg-red-700 transition">
                Close
            </button>
        </div>
    `;

    document.body.appendChild(modal);

    // Click outside to close
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.remove();
        }
    });

    // ESC key to close
    const escHandler = (e) => {
        if (e.key === 'Escape') {
            modal.remove();
            document.removeEventListener('keydown', escHandler);
        }
    };
    document.addEventListener('keydown', escHandler);
}

// ========================================
// TOAST NOTIFICATION SYSTEM
// ========================================
// For quick success/info messages

// Toast notification system (enhanced)
function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;

    // Add icon based on type
    const icons = {
        'success': '✓',
        'error': '✕',
        'info': 'ℹ',
        'warning': '⚠'
    };

    toast.innerHTML = `
        <span class="toast-icon">${icons[type] || ''}</span>
        <span>${message}</span>
    `;

    document.body.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('fade-out');
        setTimeout(() => toast.remove(), 300);
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
