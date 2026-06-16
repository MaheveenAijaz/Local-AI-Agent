/**
 * Local AI Agent - Frontend JavaScript
 * Handles authentication, API calls, and UI interactions
 */

// API Base URL
const API_BASE = window.location.origin;

// Login function
async function loginUser(username, password) {
    try {
        const response = await fetch(`${API_BASE}/api/login`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ username, password })
        });
        
        const data = await response.json();
        
        if (data.success) {
            // ✅ FIXED: Redirect to Local AI Agent Dashboard (index.html)
            window.location.href = data.redirect || '/index.html';
        } else {
            showNotification(data.message || 'Login failed', 'error');
        }
    } catch (error) {
        console.error('Login error:', error);
        showNotification('Network error. Please try again.', 'error');
    }
}

// Signup function
async function signupUser(username, password, email) {
    try {
        const response = await fetch(`${API_BASE}/api/signup`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ username, password, email })
        });
        
        const data = await response.json();
        
        if (data.success) {
            // ✅ FIXED: Redirect to Local AI Agent Dashboard after signup
            window.location.href = data.redirect || '/index.html';
        } else {
            showNotification(data.message || 'Signup failed', 'error');
        }
    } catch (error) {
        console.error('Signup error:', error);
        showNotification('Network error. Please try again.', 'error');
    }
}

// Check authentication status
async function checkAuth() {
    try {
        const response = await fetch(`${API_BASE}/api/check-auth`);
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Auth check error:', error);
        return { authenticated: false };
    }
}

// Logout function
async function logout() {
    try {
        const response = await fetch(`${API_BASE}/api/logout`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        const data = await response.json();
        if (data.success) {
            window.location.href = '/login.html';
        }
    } catch (error) {
        console.error('Logout error:', error);
    }
}

// Show notification
function showNotification(message, type = 'info') {
    // Remove existing notifications
    const existing = document.querySelector('.notification');
    if (existing) existing.remove();
    
    // Create notification
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.innerHTML = `
        <span>${message}</span>
        <button onclick="this.parentElement.remove()">&times;</button>
    `;
    
    // Add styles if not present
    if (!document.querySelector('#notification-styles')) {
        const style = document.createElement('style');
        style.id = 'notification-styles';
        style.textContent = `
            .notification {
                position: fixed;
                top: 20px;
                right: 20px;
                padding: 15px 20px;
                border-radius: 8px;
                color: white;
                display: flex;
                align-items: center;
                justify-content: space-between;
                min-width: 300px;
                max-width: 500px;
                z-index: 1000;
                animation: slideIn 0.3s ease;
            }
            .notification-info { background: #3498db; }
            .notification-success { background: #27ae60; }
            .notification-error { background: #e74c3c; }
            .notification button {
                background: none;
                border: none;
                color: white;
                font-size: 20px;
                cursor: pointer;
                margin-left: 15px;
            }
            @keyframes slideIn {
                from { transform: translateX(100%); opacity: 0; }
                to { transform: translateX(0); opacity: 1; }
            }
        `;
        document.head.appendChild(style);
    }
    
    document.body.appendChild(notification);
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
        if (notification.parentElement) {
            notification.remove();
        }
    }, 5000);
}

// Initialize authentication check on page load
document.addEventListener('DOMContentLoaded', function() {
    // Only run auth check on pages that need it (not login/signup)
    const currentPage = window.location.pathname;
    if (!currentPage.includes('login.html') && !currentPage.includes('signup.html')) {
        checkAuth().then(data => {
            if (!data.authenticated) {
                window.location.href = '/login.html';
            }
        });
    }
});

// File upload handler
async function uploadFile(file) {
    const formData = new FormData();
    formData.append('file', file);
    
    try {
        const response = await fetch(`${API_BASE}/backend/api/analyse-file`, {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Upload error:', error);
        return { success: false, error: 'Upload failed' };
    }
}

// AI Generation
async function generateAIResponse(prompt, model = 'default') {
    try {
        const response = await fetch(`${API_BASE}/api/ai/generate`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ prompt, model })
        });
        
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('AI generation error:', error);
        return { success: false, error: 'AI service unavailable' };
    }
}

// Load available models
async function loadModels() {
    try {
        const response = await fetch(`${API_BASE}/backend/api/models`);
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Models load error:', error);
        return { success: false, models: [] };
    }
}

// Export functions for use in HTML
window.loginUser = loginUser;
window.signupUser = signupUser;
window.logout = logout;
window.uploadFile = uploadFile;
window.generateAIResponse = generateAIResponse;
window.loadModels = loadModels;
window.showNotification = showNotification;