import FlowWorkspace from "@/components/flows/flow-workspace";
import DirectorArrival from "@/components/flows/director-arrival";

export default async function FlowsPage({
  searchParams,
}: {
  searchParams: Promise<{ concept?: string; shot?: string; draft?: string }>;
}) {
  const params = await searchParams;
  const conceptId =
    params.concept && /^\d+$/.test(params.concept)
      ? Number(params.concept)
      : undefined;
  const shotN =
    params.shot && /^\d+$/.test(params.shot) ? Number(params.shot) : undefined;
  // no scene named: open the newest one (the standing rule: arrival is the
  // nodes). The browser-local draft is asked for by name.
  if (!conceptId && params.draft === undefined) return <DirectorArrival />;
  return (
    <FlowWorkspace
      key={`${conceptId || "draft"}:${shotN || "first"}`}
      conceptId={conceptId}
      shotN={shotN}
    />
  );
}
