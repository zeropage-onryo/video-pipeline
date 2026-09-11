import FlowWorkspace from "@/components/flows/flow-workspace";

export default async function FlowsPage({
  searchParams,
}: {
  searchParams: Promise<{ concept?: string; shot?: string }>;
}) {
  const params = await searchParams;
  const conceptId =
    params.concept && /^\d+$/.test(params.concept)
      ? Number(params.concept)
      : undefined;
  const shotN =
    params.shot && /^\d+$/.test(params.shot) ? Number(params.shot) : undefined;
  return (
    <FlowWorkspace
      key={`${conceptId || "draft"}:${shotN || "first"}`}
      conceptId={conceptId}
      shotN={shotN}
    />
  );
}
