# Inara HR Assistant

Welcome to the Chainlit edition of the Inara HR copilot. This UI wraps the existing CrewAI + Bedrock orchestration layer and keeps the following guarantees:

- Role-based access control driven by the `EXECUTIVE_EMAILS` and `EMPLOYEE_EMAILS` environment variables.
- Secure document retrieval from S3 with cache warm-up for fast answers.
- Admin actions to refresh the HR knowledge base and clear the semantic response cache when troubleshooting.
- Inline source citations pulled directly from the underlying policy corpus.

## Getting Started

Sign in with your corporate Google account to access the HR Assistant. Only authorized email addresses can access the system.

### Authentication Requirements

- You must use an email address listed in `EXECUTIVE_EMAILS` or `EMPLOYEE_EMAILS`
- If you see an authentication error, please verify:
  1. You're using the correct corporate email address
  2. Your email is authorized by the system administrator
  3. OAuth configuration is properly set up (for administrators)

### Need Help?

If you encounter any issues or need access:
- Contact the HR Tech team at `SUPPORT_CONTACT_EMAIL`
- Ensure you're using your corporate email address for authentication
- Check that your email is on the authorized users list
