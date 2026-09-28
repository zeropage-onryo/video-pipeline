"use client";

/* /studio/cut/<project> -- the editor itself. The shell sees the path and
   steps its own bar aside (data-editor), and the assistant pill stays off:
   the editor seats its agent in its own left panel.

   Client-only on purpose: the pane sizes are restored from this viewer's
   localStorage, which the server cannot see, so a server render would
   always disagree with the first client render (a hydration mismatch in
   every panel's style). Nothing on this page is worth indexing anyway. */
import dynamic from "next/dynamic";
import { useParams } from "next/navigation";

const Editor = dynamic(() => import("@/components/cut/editor").then((m) => m.Editor), {
  ssr: false,
  loading: () => null,
});

export default function EditorPage() {
  const params = useParams<{ project: string }>();
  const id = decodeURIComponent(params?.project ?? "");
  return <Editor projectId={id} />;
}
