"use client";
import { useCallback, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { IngestResult } from "@/lib/types";

interface FileUploadProps {
  onResult: (result: IngestResult) => void;
  onError: (error: string) => void;
}

export function FileUpload({ onResult, onError }: FileUploadProps) {
  const [uploading, setUploading] = useState(false);
  const [dirPath, setDirPath] = useState("");

  const handleFiles = useCallback(async (files: FileList | null) => {
    if (!files) return;
    setUploading(true);
    for (const file of Array.from(files)) {
      try { const result = await api.ingestFile(file); onResult(result); }
      catch (e) { onError(`Failed to ingest ${file.name}: ${e}`); }
    }
    setUploading(false);
  }, [onResult, onError]);

  const handleDirectory = useCallback(async () => {
    if (!dirPath.trim()) return;
    setUploading(true);
    try { const result = await api.ingestDirectory(dirPath.trim()); result.documents.forEach(onResult); }
    catch (e) { onError(`Failed to ingest directory: ${e}`); }
    setUploading(false);
  }, [dirPath, onResult, onError]);

  return (
    <div className="space-y-4">
      <div
        className="border border-dashed border-border/40 rounded px-8 py-10 text-center cursor-pointer hover:border-cyan-500/30 hover:bg-card/30 transition-all"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); handleFiles(e.dataTransfer.files); }}
        onClick={() => document.getElementById("file-input")?.click()}
      >
        <p className="text-xs text-muted-foreground/60">
          {uploading ? "processing..." : "drop files here or click to browse"}
        </p>
        <p className="text-[10px] text-muted-foreground/50 mt-2">.txt .md .json .csv</p>
        <input id="file-input" type="file" multiple accept=".txt,.md,.json,.csv" className="hidden"
          onChange={(e) => handleFiles(e.target.files)} />
      </div>
      <div className="flex gap-2">
        <Input
          placeholder="or paste a directory path..."
          value={dirPath}
          onChange={(e) => setDirPath(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleDirectory()}
          className="text-xs bg-card/30"
        />
        <Button
          size="sm"
          variant="outline"
          className="text-xs tracking-wider"
          onClick={handleDirectory}
          disabled={uploading || !dirPath.trim()}
        >
          Ingest
        </Button>
      </div>
    </div>
  );
}
