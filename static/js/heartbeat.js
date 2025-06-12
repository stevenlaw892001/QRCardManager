const heartbeatInterval = 30 * 1000; // Heartbeat interval set to 30 seconds
let lastActivity = Date.now();
let heartbeatTimer;
let isSessionExpired = false;

// Unified redirect function to handle session expiration
function redirectToLogin() {
    isSessionExpired = true;
    window.location.href = '/logout';
}

// Get CSRF token from meta tag
function getCsrfToken() {
    const tokenElement = document.querySelector('meta[name="csrf-token"]');
    return tokenElement ? tokenElement.content : '';
}

// Asynchronously check session status
async function checkSessionSync() {
    try {
        const response = await fetch('/keep-alive', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRF-Token': getCsrfToken()
            },
            credentials: 'same-origin'
        });
        if (response.status === 200) {
            const data = await response.json();
            return data.status === 'success';
        }
        return false;
    } catch (error) {
        console.error('Error checking session:', error);
        return false;
    }
}

// Asynchronously send heartbeat to keep session alive
async function sendHeartbeat() {
    try {
        const response = await fetch('/keep-alive', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRF-Token': getCsrfToken()
            },
            credentials: 'same-origin'
        });
        if (!response.ok) {
            clearInterval(heartbeatTimer);
            redirectToLogin();
            return;
        }
        const data = await response.json();
        if (data.status !== 'success') {
            console.error('Heartbeat failed:', data);
            clearInterval(heartbeatTimer);
            redirectToLogin();
        }
    } catch (error) {
        console.error('Error sending heartbeat:', error);
        clearInterval(heartbeatTimer);
        redirectToLogin();
    }
}

// Update last activity timestamp
function updateActivity() {
    lastActivity = Date.now();
}

// Debounce function to limit high-frequency event calls
function debounce(func, wait) {
    let timeout;
    return function (...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}

// Start periodic heartbeat if user is active
function startHeartbeat() {
    heartbeatTimer = setInterval(() => {
        const timeSinceLastActivity = Date.now() - lastActivity;
        if (timeSinceLastActivity < heartbeatInterval) {
            sendHeartbeat();
        }
    }, heartbeatInterval);
}

// Check session status on page load
async function initializeSessionCheck() {
    if (!(await checkSessionSync())) {
        redirectToLogin();
    }
}

// Intercept all click events on links
document.addEventListener('click', async (event) => {
    const target = event.target.closest('a');
    if (target) {
        if (target.getAttribute('data-bypass') === 'true') {
            return; // Bypass session check for links with data-bypass attribute
        }
        if (!(await checkSessionSync()) || isSessionExpired) {
            event.preventDefault();
            event.stopPropagation();
            redirectToLogin();
        }
    }
}, true);

// Intercept all form submission events
document.addEventListener('submit', async (event) => {
    if (isSessionExpired || !(await checkSessionSync())) {
        event.preventDefault();
        event.stopPropagation();
        redirectToLogin();
    }
}, true);

// Monitor user activity to update last activity timestamp
document.addEventListener('mousemove', debounce(updateActivity, 100));
document.addEventListener('keypress', updateActivity);
document.addEventListener('click', updateActivity);
document.addEventListener('scroll', debounce(updateActivity, 100));

// Initialize session check and start heartbeat on page load
window.onload = async () => {
    await initializeSessionCheck();
    if (!isSessionExpired) {
        startHeartbeat();
    }
};

// Clear heartbeat timer on page unload
window.onunload = () => clearInterval(heartbeatTimer);