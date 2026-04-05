# Simmer Cloud Worker — Current Status & Blockers

## What We're Building
A Cloud Run Job that executes simmer-sdk refinement loops triggered by Firestore events.

## Architecture
```
Orchestrator creates job doc in Firestore (status: "queued")
  → Firebase Function (onJobCreated) detects it
    → Triggers Cloud Run Job via REST API with JOB_ID + WORKSPACE_ID env vars
      → Worker reads job from Firestore, runs simmer-sdk, writes results back
```

## What's Deployed and Working
- **Cloud Run Job** `simmer-worker` — created, image deployed
- **Firebase Function** `onJobCreated` — deployed, triggers successfully
- **Worker code** (`worker-cloud/`) — reads Firestore, runs simmer, writes back
- **Trigger chain** — verified: job queued → function fires → Cloud Run Job starts

## The Blocker: Claude Code CLI in Docker on Cloud Run

### The Problem
simmer-sdk depends on `claude-agent-sdk` which spawns Claude Code CLI (`@anthropic-ai/claude-code`) as a Node.js subprocess. The CLI crashes with exit code 1 in the Cloud Run container.

### Error
```
claude_agent_sdk._errors.ProcessError: Command failed with exit code 1 (exit code: 1)
  at subprocess_cli.py line 618
  called from judge_board.py line 231 (_dispatch_single_panelist)
```

### What We've Tried
1. **Installed Node.js + Claude Code CLI in Dockerfile** — CLI installs fine, `claude --version` returns `2.1.87`
2. **Set dummy ANTHROPIC_API_KEY** — simmer-sdk now auto-sets `bedrock-mode-no-key-needed` in Bedrock mode (fix merged to simmer-sdk)
3. **Dockerfile env fixes** — tried `HOME=/root`, `mkdir /root/.claude`, `CLAUDECODE=""`

### Docker Build Issue
The `--no-cache` rebuild failed because Node.js 20 installation broke:
```
dpkg-deb: error: paste subprocess was killed by signal (Broken pipe)
E: Sub-process /usr/bin/dpkg returned an error code (1)
```
This means the latest image being tested does NOT have the HOME/.claude fixes — it's still the old image.

### Root Cause Analysis (from research)
Three likely causes for the CLI crashing in Cloud Run:

1. **No writable HOME/.claude directory** — CLI needs `~/.claude/` for config/state. If missing, crashes on startup.
   - Fix: `ENV HOME=/root` + `RUN mkdir -p /root/.claude`

2. **CLAUDECODE env var inherited** — If set, CLI thinks it's inside another Claude session and refuses to start.
   - Fix: `ENV CLAUDECODE=""`

3. **First-run acceptance flow** — CLI has a terms acceptance that can't run non-interactively.
   - Fix: `ENV CLAUDE_ACCEPT_TOS=1` or pre-create acceptance files

4. **Node.js install is breaking** — nodesource setup script is flaky on `python:3.13-slim` base image. Need alternative Node.js install method.

### What Needs to Happen Next

#### Step 1: Fix Node.js installation in Dockerfile
The nodesource install script is broken. Use a multi-stage build or different Node.js install method:
```dockerfile
# Option A: Use official Node image as base
FROM node:20-slim AS node-base
FROM python:3.13-slim
COPY --from=node-base /usr/local/bin/node /usr/local/bin/node
COPY --from=node-base /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm

# Option B: Use nvm
RUN curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.0/install.sh | bash && \
    . ~/.nvm/nvm.sh && nvm install 20

# Option C: Direct binary download
RUN curl -fsSL https://nodejs.org/dist/v20.18.0/node-v20.18.0-linux-x64.tar.xz | \
    tar -xJ --strip-components=1 -C /usr/local/
```

#### Step 2: Add Claude Code environment setup
```dockerfile
ENV HOME=/root
ENV CLAUDECODE=""
RUN mkdir -p /root/.claude
RUN npm install -g @anthropic-ai/claude-code
RUN which claude && claude --version
```

#### Step 3: Test locally before pushing
```bash
docker run --platform linux/amd64 \
  -e ANTHROPIC_API_KEY=bedrock-mode-no-key-needed \
  -e AWS_ACCESS_KEY=... \
  -e AWS_SECRET_KEY=... \
  -e AWS_REGION=us-east-1 \
  simmer-worker:test \
  python -c "
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
import asyncio
async def test():
    options = ClaudeAgentOptions(model='claude-sonnet-4-6')
    async with ClaudeSDKClient(options=options) as client:
        result = await client.query('Say hello in one word')
        print(result)
asyncio.run(test())
"
```

#### Step 4: Rebuild, push, update Cloud Run Job
```bash
docker build --platform linux/amd64 -t ...simmer-worker:v4 worker-cloud/
docker push ...simmer-worker:v4
gcloud run jobs update simmer-worker --image=...simmer-worker:v4
```

#### Step 5: Trigger test
```bash
curl -X POST https://orrery-orchestrator-469580747258.us-central1.run.app/simmer/general
# Firebase Function will auto-trigger the Cloud Run Job
```

## File Locations
- Worker code: `worker-cloud/worker/` (main.py, jobs/simmer_general.py, jobs/extract_batch.py)
- Dockerfile: `worker-cloud/Dockerfile`
- simmer-sdk: `worker-cloud/simmer-sdk/` (copied from ../simmer-sdk, NOT a git submodule)
- Firebase Function: `functions/index.js`
- Cloud Run Job name: `simmer-worker`
- Region: `us-central1`
- Project: `noospheric-orrery`

## Environment Variables on Cloud Run Job
```
FIREBASE_PROJECT_ID=noospheric-orrery
AWS_ACCESS_KEY=<your-aws-access-key>
AWS_SECRET_KEY=<your-aws-secret-key>
AWS_REGION=us-east-1
CLASSIFICATION_MODEL=us.anthropic.claude-sonnet-4-20250514-v1:0
EXTRACTION_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0
SIMMER_ITERATIONS=5
VERTEX_AI_REGION=us-central1
```

## What Works If Simmer Succeeds
1. Spec stored in Firestore
2. Iteration history stored (visible in simmer detail UI)
3. Batch extraction job auto-queued
4. Firebase Function triggers batch extraction Cloud Run Job
5. All docs re-extracted with new spec
6. New entities auto-embedded via Vertex AI
7. Full pipeline operational on cloud
