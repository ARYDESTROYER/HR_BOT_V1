# Inara HR Assistant

Welcome to the Chainlit edition of the Inara HR copilot. This UI wraps the existing CrewAI + Bedrock orchestration layer and keeps the following guarantees:

- Role-based access control driven by the `EXECUTIVE_EMAILS` and `EMPLOYEE_EMAILS` environment variables.
- Secure document retrieval from S3 with cache warm-up for fast answers.
- Admin actions to refresh the HR knowledge base and clear the semantic response cache when troubleshooting.
- Inline source citations pulled directly from the underlying policy corpus.

Sign in with your corporate Google account to get started. Need help? Contact the HR Tech team at `SUPPORT_CONTACT_EMAIL`.
