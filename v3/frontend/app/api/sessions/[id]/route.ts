import { callBackend } from "@/lib/backend";

export const dynamic = "force-dynamic";

// Clears the server-side memory for a chat when it is deleted in the sidebar.
export async function DELETE(_req: Request, { params }: { params: { id: string } }) {
  return callBackend(`/api/sessions/${encodeURIComponent(params.id)}`, { method: "DELETE" });
}
