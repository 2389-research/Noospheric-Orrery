"use client";
import { useState } from "react";
import { FileUpload } from "@/components/file-upload";
import { UploadStatus } from "@/components/upload-status";
import { IngestResult } from "@/lib/types";

export default function UploadPage() {
  const [results, setResults] = useState<IngestResult[]>([]);
  const [errors, setErrors] = useState<string[]>([]);
  return (
    <div className="max-w-2xl mx-auto space-y-8">
      <div>
        <h1 className="text-sm tracking-[4px] text-muted-foreground uppercase">Ingest</h1>
        <p className="text-muted-foreground/90 text-xs mt-2">Upload text files or point at a directory to start building the knowledge graph.</p>
      </div>
      <FileUpload onResult={(r) => setResults((prev) => [...prev, r])} onError={(e) => setErrors((prev) => [...prev, e])} />
      <UploadStatus results={results} errors={errors} />
    </div>
  );
}
