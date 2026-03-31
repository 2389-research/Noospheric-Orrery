/**
 * Firestore-triggered functions for the Noospheric Orrery.
 *
 * When a job document is created with status "queued", this function
 * dispatches it to the worker Cloud Run service via HTTP.
 * The worker handles long-running tasks (simmer, extract).
 *
 * Architecture:
 *   Firestore write → this function → HTTP to worker Cloud Run → results to Firestore
 */

const { onDocumentCreated } = require("firebase-functions/v2/firestore");
const { defineString } = require("firebase-functions/params");
const admin = require("firebase-admin");

admin.initializeApp();

// Cloud Run service URLs
const ORCHESTRATOR_URL = defineString("ORCHESTRATOR_URL", {
  default: "https://orrery-orchestrator-469580747258.us-central1.run.app",
});

/**
 * Trigger: new job document created.
 * Marks job as running and dispatches to the appropriate handler.
 *
 * For now, simmer jobs require the worker service.
 * Normalization and search rebuild can run via orchestrator API.
 */
exports.onJobCreated = onDocumentCreated(
  {
    document: "workspaces/{workspaceId}/jobs/{jobId}",
    region: "us-central1",
    timeoutSeconds: 540,
    memory: "256MiB",
  },
  async (event) => {
    const snapshot = event.data;
    if (!snapshot) return;

    const job = snapshot.data();
    const jobId = event.params.jobId;
    const workspaceId = event.params.workspaceId;

    if (job.status !== "queued") return;

    console.log(`Job created: ${job.type} [${jobId}] workspace=${workspaceId}`);

    const baseUrl = ORCHESTRATOR_URL.value();

    try {
      switch (job.type) {
        case "simmer_general":
        case "simmer_domain":
        case "extract_batch":
          // These need the Python worker with simmer-sdk.
          // Log for now — worker Cloud Run service will be deployed next.
          console.log(`${job.type} job ${jobId}: requires Python worker service`);
          break;

        default:
          console.log(`Unknown job type: ${job.type}`);
      }
    } catch (error) {
      console.error(`Job ${jobId} error:`, error);
      await snapshot.ref.update({
        status: "failed",
        completedAt: admin.firestore.FieldValue.serverTimestamp(),
        result: { error: error.message },
      });
    }
  }
);

/**
 * Trigger: new document ingested.
 * Logs the event. Future: auto-trigger search reindex, normalization.
 */
exports.onDocumentIngested = onDocumentCreated(
  {
    document: "workspaces/{workspaceId}/documents/{docId}",
    region: "us-central1",
    timeoutSeconds: 30,
    memory: "128MiB",
  },
  async (event) => {
    const docId = event.params.docId;
    const workspaceId = event.params.workspaceId;
    console.log(`Document ingested: ${docId} in workspace ${workspaceId}`);
  }
);
