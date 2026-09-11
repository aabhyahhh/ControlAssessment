import { FileUp, FolderUp, Paperclip, Send } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState, type FormEvent } from "react";

export interface ChatInputHandle {
  setText: (text: string) => void;
}

interface ChatInputProps {
  onSend: (message: string) => void;
  onFileSelect?: (file: File) => void;
  onFolderSelect?: (files: FileList) => void;
  disabled?: boolean;
  placeholder?: string;
  /** Accept string for the single-file picker (varies by phase). */
  acceptFile?: string;
  showUpload?: boolean;
}

/**
 * The attach button opens a small menu with both options rather than
 * guessing from the active phase — a user may legitimately want to re-upload
 * an RCM while sitting on Phase 3, and phase-guessing made that impossible.
 */
const ChatInput = forwardRef<ChatInputHandle, ChatInputProps>(function ChatInput(
  { onSend, onFileSelect, onFolderSelect, disabled, placeholder, acceptFile, showUpload },
  ref,
) {
  const [text, setText] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const folderRef = useRef<HTMLInputElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  useImperativeHandle(ref, () => ({ setText: (value: string) => setText(value) }));

  // Close the menu on an outside click or Escape.
  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText("");
  };

  return (
    <form className="chat-input-area" onSubmit={handleSubmit}>
      {showUpload && (
        <div className="chat-upload-wrap" ref={wrapRef}>
          <input
            ref={fileRef}
            type="file"
            accept={acceptFile}
            style={{ display: "none" }}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) onFileSelect?.(file);
              e.target.value = "";
              setMenuOpen(false);
            }}
          />
          <input
            ref={folderRef}
            type="file"
            multiple
            {...{ webkitdirectory: "", directory: "" }}
            style={{ display: "none" }}
            onChange={(e) => {
              if (e.target.files && e.target.files.length > 0) onFolderSelect?.(e.target.files);
              e.target.value = "";
              setMenuOpen(false);
            }}
          />

          <button
            type="button"
            className="chat-upload-btn"
            disabled={disabled}
            onClick={() => setMenuOpen((v) => !v)}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            title="Attach"
          >
            <Paperclip size={16} />
          </button>

          {menuOpen && (
            <div className="chat-upload-menu" role="menu">
              <button type="button" role="menuitem" onClick={() => fileRef.current?.click()}>
                <FileUp size={15} />
                <span>
                  <strong>Attach file</strong>
                  <em>RCM, an SOP or workpaper, or an edited workbook</em>
                </span>
              </button>
              <button type="button" role="menuitem" onClick={() => folderRef.current?.click()}>
                <FolderUp size={15} />
                <span>
                  <strong>Attach folder</strong>
                  <em>SOPs/workpapers or evidence — one subfolder per Control ID</em>
                </span>
              </button>
            </div>
          )}
        </div>
      )}

      <input
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={placeholder ?? "Message the assessment agent…"}
        disabled={disabled}
        className="chat-input-field"
      />
      <button type="submit" className="chat-input-send" disabled={disabled || !text.trim()}>
        <Send size={16} />
      </button>
    </form>
  );
});

export default ChatInput;
