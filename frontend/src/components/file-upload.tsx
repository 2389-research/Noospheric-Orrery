"use client";
import { useCallback, useState } from "react";
import { api } from "@/lib/api";
import { IngestResult } from "@/lib/types";

interface FileUploadProps {
  onResult: (result: IngestResult) => void;
  onError: (error: string) => void;
}

export function FileUpload({ onResult, onError }: FileUploadProps) {
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState({ current: 0, total: 0 });

  const handleFiles = useCallback(async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const fileArr = Array.from(files).filter(f =>
      [".txt", ".md", ".json", ".csv", ".jpg", ".jpeg", ".png", ".webp", ".gif"].some(ext => f.name.toLowerCase().endsWith(ext))
    );
    if (fileArr.length === 0) {
      onError("No supported files found (.txt, .md, .json, .csv, .jpg, .png, .webp)");
      return;
    }

    setUploading(true);
    setProgress({ current: 0, total: fileArr.length });

    for (let i = 0; i < fileArr.length; i++) {
      const file = fileArr[i];
      setProgress({ current: i + 1, total: fileArr.length });
      try {
        const result = await api.ingestFile(file);
        onResult(result);
      } catch (e) {
        onError(`Failed: ${file.name} — ${e}`);
      }
    }

    setUploading(false);
    setProgress({ current: 0, total: 0 });
  }, [onResult, onError]);

  return (
    <div className="space-y-4">
      <div
        role="button"
        tabIndex={0}
        aria-label="Upload files — drop files here or press Enter to browse"
        className="border border-dashed border-border/40 rounded px-8 py-10 text-center cursor-pointer hover:border-cyan-500/30 hover:bg-card/30 transition-all focus:outline-none focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/30"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); handleFiles(e.dataTransfer.files); }}
        onClick={() => document.getElementById("file-input")?.click()}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); document.getElementById("file-input")?.click(); } }}
      >
        {uploading ? (
          <div className="space-y-2">
            <p className="text-xs text-cyan-400/80">
              ingesting {progress.current} of {progress.total}...
            </p>
            <div className="w-48 mx-auto h-1 bg-card rounded overflow-hidden">
              <div
                className="h-full bg-cyan-500/50 transition-all"
                style={{ width: `${progress.total > 0 ? (progress.current / progress.total) * 100 : 0}%` }}
              />
            </div>
          </div>
        ) : (
          <>
            <p className="text-xs text-muted-foreground/90">
              Drop files here or click to browse.
            </p>
            <p className="text-[10px] text-muted-foreground/50 mt-2">
              .txt .md .json .csv .jpg .png .webp — multiple files supported.
            </p>
          </>
        )}
        <input
          id="file-input"
          type="file"
          multiple
          accept=".txt,.md,.json,.csv,.jpg,.jpeg,.png,.webp,.gif"
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
        {/* Hidden input for directory selection */}
        <input
          id="dir-input"
          type="file"
          // @ts-expect-error webkitdirectory is non-standard but widely supported
          webkitdirectory=""
          directory=""
          multiple
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
      </div>
      {!uploading && (
        <button
          onClick={() => document.getElementById("dir-input")?.click()}
          className="w-full text-[10px] text-muted-foreground/50 hover:text-muted-foreground/80 transition-colors py-1"
        >
          or select a folder
        </button>
      )}
    </div>
  );
}
