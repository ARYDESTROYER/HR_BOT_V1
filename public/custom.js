/**
 * Custom JavaScript to fix authentication error display
 * This script clears authentication error parameters from the URL
 * to prevent stale error messages from showing on page reload
 */

(function() {
    'use strict';
    
    // Check if there's an error parameter in the URL
    const urlParams = new URLSearchParams(window.location.search);
    const error = urlParams.get('error');
    
    // If there's a credentialssignin error, clear it from the URL
    // This prevents the error from showing on subsequent page loads
    if (error === 'credentialssignin' || error === 'credentialsSignin') {
        console.log('[Inara] Clearing authentication error from URL');
        
        // Remove the error parameter
        urlParams.delete('error');
        
        // Build new URL without the error parameter
        const newUrl = window.location.pathname + 
            (urlParams.toString() ? '?' + urlParams.toString() : '') + 
            window.location.hash;
        
        // Replace the current URL without reloading the page
        window.history.replaceState({}, document.title, newUrl);
    }
    
    // Monitor for error notifications and improve their display
    const observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            mutation.addedNodes.forEach(function(node) {
                // Check if this is a notification element
                if (node.nodeType === 1 && node.textContent) {
                    const text = node.textContent.trim();
                    
                    // Check if it contains the untranslated error key
                    if (text.includes('credentialssignin') || text === ': credentialssignin') {
                        console.log('[Inara] Found untranslated error notification');
                        
                        // Replace with the translated message
                        const translatedMessage = 'Sign in failed. Check the details you provided are correct';
                        
                        // Try to update the text content
                        if (node.textContent === ': credentialssignin') {
                            node.textContent = translatedMessage;
                        } else if (node.textContent.includes(': credentialssignin')) {
                            node.textContent = node.textContent.replace(
                                ': credentialssignin',
                                translatedMessage
                            );
                        } else if (node.textContent.includes('credentialssignin')) {
                            node.textContent = node.textContent.replace(
                                'credentialssignin',
                                translatedMessage
                            );
                        }
                    }
                }
            });
        });
    });
    
    // Start observing the document for changes
    observer.observe(document.body, {
        childList: true,
        subtree: true
    });
    
    console.log('[Inara] Custom error handling initialized');
})();
