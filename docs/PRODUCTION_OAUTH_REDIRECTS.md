# Production OAuth Redirect URLs

Panopticon is deployed at:

```text
Frontend: https://panopticon-frontend-226094931757.us-central1.run.app
Backend:  https://panopticon-backend-226094931757.us-central1.run.app
```

The backend Cloud Run service is already configured with these callback URLs:

```text
Google OAuth:
https://panopticon-backend-226094931757.us-central1.run.app/api/auth/google/callback

GitLab OAuth:
https://panopticon-backend-226094931757.us-central1.run.app/api/integrations/gitlab/callback

Slack OAuth:
https://panopticon-backend-226094931757.us-central1.run.app/api/integrations/slack/callback
```

These URLs must also be registered in the provider dashboards:

- Google Cloud Console -> APIs & Services -> Credentials -> OAuth client -> Authorized redirect URIs.
- GitLab -> User Settings -> Applications or project/group OAuth application -> Redirect URI.
- Slack API Dashboard -> OAuth & Permissions -> Redirect URLs.

This provider-side registration cannot be completed from the codebase unless those external dashboards expose an authorized management API/token for this specific app.

## Verification

After registering the provider-side redirect URLs, run these from the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\gcp_smoke_auth_flow.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\gcp_smoke_cloud_run.ps1
```

Expected results:

```text
auth_smoke=passed
google_oauth_start=HTTP 307
gitlab_oauth_connect=HTTP 307
slack_oauth_connect=HTTP 307
```

The auth smoke test verifies CSRF, signup, production session cookies, authenticated session lookup, logout, login, and session lookup again. The Cloud Run smoke test verifies the deployed backend/frontend, Gemini status, MCP tools, and OAuth redirect generation.
