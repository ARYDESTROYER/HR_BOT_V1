# Authentication Error Fix

## Issue
When visiting the Chainlit landing page, users may see a notification displaying `: credentialssignin` in the top right corner. This is an authentication error that should show a translated message like "Sign in failed. Check the details you provided are correct" but instead displays the raw translation key.

## Root Cause
This issue occurs when:
1. OAuth credentials are not properly configured in the `.env` file
2. A user attempts to authenticate with an unauthorized email address
3. There's a previous failed authentication attempt with an error parameter in the URL

The error appears because Chainlit redirects to `/?error=credentialssignin` after a failed authentication, and the frontend doesn't properly translate the error key to its human-readable message.

## Solution

### 1. Configure OAuth Credentials
Ensure your `.env` file has valid OAuth credentials:
```bash
OAUTH_GOOGLE_CLIENT_ID=your_google_client_id
OAUTH_GOOGLE_CLIENT_SECRET=your_google_client_secret
```

### 2. Verify Authorized Emails
Make sure the user's email is listed in either:
```bash
EXECUTIVE_EMAILS=user1@company.com,user2@company.com
EMPLOYEE_EMAILS=user3@company.com,user4@company.com
```

### 3. Configuration Updates
The following changes were made to fix the translation issue:

#### `.chainlit/config.toml`
Added `default_language = "en-US"` to the `[UI]` section to ensure translations are properly loaded.

#### `src/hr_bot/ui/chainlit_app.py`
- Added OAuth configuration validation warnings
- Added `on_app_startup` hook to log configuration status
- Added warnings when OAuth credentials are missing

#### Login Page Documentation
Updated `chainlit.md` and language variants to provide clearer authentication guidance.

## Workaround (If Issue Persists)

If the error message still appears as an untranslated key, you can use the custom JavaScript fix:

1. The `public/custom.js` file contains code that:
   - Clears the error parameter from the URL
   - Monitors for untranslated error notifications
   - Replaces them with the correct translated message

2. To use this workaround, you may need to manually include the script in your deployment or wait for a Chainlit update that fixes this translation issue.

## Prevention

To prevent this error from appearing:
1. Always configure OAuth credentials before deploying
2. Ensure all expected users are in the authorized email lists
3. Monitor application logs for OAuth configuration warnings
4. Test authentication with authorized and unauthorized emails before production deployment

## Testing

To test the fix:
1. Start the Chainlit app: `chainlit run src/hr_bot/ui/chainlit_app.py --host 0.0.0.0 --port 8501`
2. Check the logs for OAuth configuration status
3. Attempt to log in with an authorized email
4. Attempt to log in with an unauthorized email (should show proper error message)
5. Verify that the error notification displays translated text, not the raw key

## Related Files
- `.chainlit/config.toml` - UI configuration with language settings
- `.chainlit/translations/en-US.json` - English (US) translations including error messages
- `src/hr_bot/ui/chainlit_app.py` - Authentication callbacks and validation
- `chainlit.md` - Login page content with authentication guidance
- `public/custom.js` - Optional client-side fix for translation issues

## Additional Notes

This issue is related to how Chainlit 2.9.0 handles authentication error display. The fixes implemented here work around the translation issue by:
1. Ensuring proper configuration
2. Adding better logging and warnings
3. Improving user-facing documentation
4. Providing an optional client-side workaround

If you continue to experience issues, please check:
- Chainlit version (`chainlit --version`)
- Browser console for JavaScript errors
- Application logs for OAuth configuration warnings
- That translation files are present in `.chainlit/translations/`
