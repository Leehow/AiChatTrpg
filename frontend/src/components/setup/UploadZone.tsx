import { useRef, useState, type DragEvent, type ReactNode } from "react";

interface UploadZoneProps {
  accept: string;
  onFile: (file: File) => void | Promise<void>;
  disabled?: boolean;
  children: ReactNode;
  className?: string;
}

export function UploadZone({
  accept,
  onFile,
  disabled,
  children,
  className,
}: UploadZoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  const trigger = () => {
    if (disabled) return;
    inputRef.current?.click();
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    if (disabled) return;
    const file = e.dataTransfer.files?.[0];
    if (file) void onFile(file);
  };

  const onDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    if (!disabled) setDragOver(true);
  };

  const onDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
  };

  return (
    <div
      role="button"
      tabIndex={disabled ? -1 : 0}
      onClick={trigger}
      onKeyDown={(e) => {
        if (!disabled && (e.key === "Enter" || e.key === " ")) trigger();
      }}
      onDrop={onDrop}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      aria-disabled={disabled}
      className={[
        "border-[1.5px] border-dashed rounded-xl p-7 text-center cursor-pointer",
        "transition-colors duration-150",
        "bg-surface",
        dragOver ? "border-accent bg-accent-dim" : "border-border-2",
        disabled ? "opacity-50 cursor-not-allowed" : "hover:border-accent hover:bg-accent-dim",
        className || "",
      ].join(" ")}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void onFile(f);
          e.target.value = "";
        }}
      />
      {children}
    </div>
  );
}
