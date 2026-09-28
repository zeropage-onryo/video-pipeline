"use client";

/* /studio/cut/<project> -- the editor itself. The shell sees the path and
   steps its own bar aside (data-editor), and the assistant pill stays off:
   the editor seats its agent in its own left panel. */
import { useParams } from "next/navigation";
import { Editor } from "@/components/cut/editor";

export default function EditorPage() {
  const params = useParams<{ project: string }>();
  const id = decodeURIComponent(params?.project ?? "");
  return <Editor projectId={id} />;
}
