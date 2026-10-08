"use client";

/* A page's deep link, read without making the whole page wait (2026-10-08).
   The ⌘K palette opens an element as /studio/elements?open=character-3 and
   a render as /studio/assets?open=82 -- and useSearchParams needs a Suspense
   boundary above it for the static build, which those pages never had. This
   puts the boundary around nothing but the reader, and calls `onParams`
   whenever the query string changes: a palette choice made ON the page it
   targets changes the URL without remounting the page. */
import { Suspense, useEffect, useRef } from "react";
import { useSearchParams } from "next/navigation";

function Reader({ onParams }: { onParams: (params: URLSearchParams) => void }) {
  const params = useSearchParams();
  const key = params.toString();
  const latest = useRef(onParams);
  useEffect(() => {
    latest.current = onParams;
  });
  useEffect(() => {
    latest.current(new URLSearchParams(key));
  }, [key]);
  return null;
}

export function UrlParams({ onParams }: { onParams: (params: URLSearchParams) => void }) {
  return (
    <Suspense fallback={null}>
      <Reader onParams={onParams} />
    </Suspense>
  );
}
