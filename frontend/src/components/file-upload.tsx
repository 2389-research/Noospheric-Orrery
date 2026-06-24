"use client";
import { useCallback, useState } from "react";
import { api } from "@/lib/api";
import { IngestResult } from "@/lib/types";

interface FileUploadProps {
  onResult: (result: IngestResult) => void;
  onError: (error: string) => void;
}

const TEXT_EXTS = [".txt", ".md", ".json", ".csv", ".dip"];
const IMAGE_EXTS = [".jpg", ".jpeg", ".png", ".webp", ".gif"];
const FILE_EXTS = [".pdf", ".docx", ".ipynb", ".py", ".ts", ".tsx", ".js", ".jsx", ".sql", ".yaml", ".yml", ".toml", ".sh"];
const ALL_EXTS = [...TEXT_EXTS, ...IMAGE_EXTS, ...FILE_EXTS];

export function FileUpload({ onResult, onError }: FileUploadProps) {
  const [uploadingType, setUploadingType] = useState<"text" | "image" | "any" | null>(null);
  const [progress, setProgress] = useState({ current: 0, total: 0 });

  const handleFiles = useCallback(async (files: FileList | null, type: "text" | "image" | "any" | "all" = "all") => {
    if (!files || files.length === 0) return;
    const allowedExts = type === "text" ? TEXT_EXTS : type === "image" ? IMAGE_EXTS : type === "any" ? FILE_EXTS : ALL_EXTS;
    const fileArr = Array.from(files).filter(f =>
      allowedExts.some(ext => f.name.toLowerCase().endsWith(ext))
    );
    if (fileArr.length === 0) {
      onError(`No supported files found (${allowedExts.join(", ")})`);
      return;
    }

    const inferredType: "text" | "image" | "any" = type === "all"
      ? (fileArr.some(f => IMAGE_EXTS.some(ext => f.name.toLowerCase().endsWith(ext))) ? "image" : "text")
      : type;
    setUploadingType(inferredType);
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

    setUploadingType(null);
    setProgress({ current: 0, total: 0 });
  }, [onResult, onError]);

  return (
    <div className="space-y-4">
      {/* Text documents */}
      <div
        role="button"
        tabIndex={0}
        aria-label="Upload text documents"
        className={`border border-dashed rounded px-8 py-8 text-center transition-all focus:outline-none ${
          uploadingType === "image" ? "opacity-40 pointer-events-none border-border/20" :
          "border-border/40 cursor-pointer hover:border-cyan-500/30 hover:bg-card/30 focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/30"
        }`}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); handleFiles(e.dataTransfer.files, "text"); }}
        onClick={() => !uploadingType && document.getElementById("text-file-input")?.click()}
        onKeyDown={(e) => { if (!uploadingType && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); document.getElementById("text-file-input")?.click(); } }}
      >
        {uploadingType === "text" ? (
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
              Documents — drop files or click to browse
            </p>
            <p className="text-[10px] text-muted-foreground/70 mt-2">
              .txt .md .json .csv .dip — multiple files supported
            </p>
          </>
        )}
        <input
          id="text-file-input"
          type="file"
          multiple
          accept=".txt,.md,.json,.csv,.dip"
          className="hidden"
          onChange={(e) => handleFiles(e.target.files, "text")}
        />
      </div>

      {/* Images */}
      <div
        role="button"
        tabIndex={0}
        aria-label="Upload images"
        className={`border border-dashed rounded px-8 py-8 text-center transition-all focus:outline-none ${
          uploadingType === "text" ? "opacity-40 pointer-events-none border-border/20" :
          "border-emerald-500/20 cursor-pointer hover:border-emerald-500/30 hover:bg-card/30 focus:border-emerald-500/50 focus:ring-1 focus:ring-emerald-500/30"
        }`}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); handleFiles(e.dataTransfer.files, "image"); }}
        onClick={() => !uploadingType && document.getElementById("image-file-input")?.click()}
        onKeyDown={(e) => { if (!uploadingType && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); document.getElementById("image-file-input")?.click(); } }}
      >
        {uploadingType === "image" ? (
          <div className="space-y-2">
            <p className="text-xs text-emerald-400/80">
              ingesting {progress.current} of {progress.total}...
            </p>
            <div className="w-48 mx-auto h-1 bg-card rounded overflow-hidden">
              <div
                className="h-full bg-emerald-500/50 transition-all"
                style={{ width: `${progress.total > 0 ? (progress.current / progress.total) * 100 : 0}%` }}
              />
            </div>
          </div>
        ) : (
          <>
            <p className="text-xs text-muted-foreground/90">
              Images — drop files or click to browse
            </p>
            <p className="text-[10px] text-muted-foreground/70 mt-2">
              .jpg .png .webp .gif — entities extracted on upload
            </p>
          </>
        )}
        <input
          id="image-file-input"
          type="file"
          multiple
          accept=".jpg,.jpeg,.png,.webp,.gif"
          className="hidden"
          onChange={(e) => handleFiles(e.target.files, "image")}
        />
      </div>

      {/* Any file */}
      <div
        role="button"
        tabIndex={0}
        aria-label="Upload any file"
        className={`border border-dashed rounded px-8 py-8 text-center transition-all focus:outline-none ${
          uploadingType === "text" || uploadingType === "image" ? "opacity-40 pointer-events-none border-border/20" :
          "border-violet-500/20 cursor-pointer hover:border-violet-500/30 hover:bg-card/30 focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30"
        }`}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); handleFiles(e.dataTransfer.files, "any"); }}
        onClick={() => !uploadingType && document.getElementById("any-file-input")?.click()}
        onKeyDown={(e) => { if (!uploadingType && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); document.getElementById("any-file-input")?.click(); } }}
      >
        {uploadingType === "any" ? (
          <div className="space-y-2">
            <p className="text-xs text-violet-400/80">
              ingesting {progress.current} of {progress.total}...
            </p>
            <div className="w-48 mx-auto h-1 bg-card rounded overflow-hidden">
              <div
                className="h-full bg-violet-500/50 transition-all"
                style={{ width: `${progress.total > 0 ? (progress.current / progress.total) * 100 : 0}%` }}
              />
            </div>
          </div>
        ) : (
          <>
            <p className="text-xs text-muted-foreground/90">
              Any file — drop files or click to browse
            </p>
            <p className="text-[10px] text-muted-foreground/70 mt-2">
              .pdf .docx .ipynb .py .ts .sql and more
            </p>
          </>
        )}
        <input
          id="any-file-input"
          type="file"
          multiple
          accept=".pdf,.docx,.ipynb,.py,.ts,.tsx,.js,.jsx,.sql,.yaml,.yml,.toml,.sh"
          className="hidden"
          onChange={(e) => handleFiles(e.target.files, "any")}
        />
      </div>

      {/* Directory upload */}
      {!uploadingType && (
        <button
          onClick={() => document.getElementById("dir-input")?.click()}
          className="w-full text-[10px] text-muted-foreground/70 hover:text-muted-foreground/80 transition-colors py-1"
        >
          or select a folder (text + images)
        </button>
      )}
      <input
        id="dir-input"
        type="file"
        // @ts-expect-error webkitdirectory is non-standard but widely supported
        webkitdirectory=""
        directory=""
        multiple
        className="hidden"
        onChange={(e) => handleFiles(e.target.files, "all")}
      />
    </div>
  );
}
