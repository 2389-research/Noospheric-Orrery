# docs/

Design specs, architecture docs, and research for Orrery.

## Directory Structure

```
docs/
├── active/       ← Current work. Specs being implemented or researched.
├── archive/      ← Completed work. Kept for reference.
```

## Rules for Agents

1. **New specs go in `active/`**. Name them `{topic}_{date}.md`.
2. **When a spec is fully implemented**, move it to `archive/`.
3. **Don't delete docs** — archive them.
4. **Don't edit archived docs** — create a new one in `active/` that supersedes it.

## Security

**NEVER include real credentials, API keys, or secrets in docs.**

Use placeholders:
```
AWS_ACCESS_KEY=<your-aws-access-key>
AWS_SECRET_KEY=<your-aws-secret-key>
ANTHROPIC_API_KEY=<your-api-key>
FIREBASE_API_KEY=<your-firebase-key>
```

This directory is checked into git. Anything written here is in the
repo history permanently. Even in a private repo, credentials in git
history are a security risk.
