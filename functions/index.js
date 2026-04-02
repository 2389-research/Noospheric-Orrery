/**
 * Firestore triggers for the Noospheric Orrery.
 *
 * When a job document is created with status "queued", dispatches
 * a Cloud Run Job to execute it.
 */

const { onDocumentCreated } = require("firebase-functions/v2/firestore");
const admin = require("firebase-admin");

admin.initializeApp();

const PROJECT_ID = process.env.GCP_PROJECT || process.env.GCLOUD_PROJECT || "noospheric-orrery";
const REGION = "us-central1";
const JOB_NAME = "simmer-worker";

exports.onJobCreated = onDocumentCreated(
  {
    document: "workspaces/{workspaceId}/jobs/{jobId}",
    region: REGION,
    timeoutSeconds: 60,
    memory: "256MiB",
  },
  async (event) => {
    const snapshot = event.data;
    if (!snapshot) return;

    const job = snapshot.data();
    const jobId = event.params.jobId;
    const workspaceId = event.params.workspaceId;

    if (job.status !== "queued") return;

    const validTypes = ["simmer_general", "simmer_golden_set", "simmer_extraction_spec", "simmer_domain", "extract_batch", "post_process"];
    if (!validTypes.includes(job.type)) return;

    console.log(`Job ${jobId} (${job.type}) queued in workspace ${workspaceId}`);

    try {
      const { GoogleAuth } = require("google-auth-library");
      const auth = new GoogleAuth();
      const client = await auth.getClient();

      const jobPath = `projects/${PROJECT_ID}/locations/${REGION}/jobs/${JOB_NAME}`;
      const url = `https://run.googleapis.com/v2/${jobPath}:run`;

      const response = await client.request({
        url,
        method: "POST",
        data: {
          overrides: {
            containerOverrides: [
              {
                env: [
                  { name: "JOB_ID", value: jobId },
                  { name: "WORKSPACE_ID", value: workspaceId },
                ],
              },
            ],
          },
        },
      });

      console.log(`Dispatched Cloud Run Job for ${jobId}:`, response.data?.metadata?.name || "ok");
    } catch (error) {
      console.error(`Failed to dispatch job ${jobId}:`, error.message);
    }
  }
);
