"use client";

// The WebGL backdrop for the hero: a slow aperture ring (ZPF's
// aperture/viewfinder logo motif, filmmaking.md) and a sparse drift of
// signal-red embers, both near-static so text stays readable on top.
// Kept deliberately cheap -- no postprocessing pipeline, low particle
// count, capped DPR -- since this renders behind copy on first paint,
// not as a standalone showpiece.

import { useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import * as THREE from "three";

const SIGNAL_RED = "#e4002b";

function ApertureRing() {
  const group = useRef<THREE.Group>(null);
  const rings = useMemo(
    () => [
      { radius: 2.6, thickness: 0.012, opacity: 0.55, speed: 0.03 },
      { radius: 3.15, thickness: 0.006, opacity: 0.3, speed: -0.018 },
      { radius: 3.55, thickness: 0.003, opacity: 0.18, speed: 0.012 },
    ],
    [],
  );

  useFrame((_, delta) => {
    if (!group.current) return;
    // Only the ring meshes are animated; the blade meshes that follow
    // them in `children` have no matching `rings` entry, so guard the
    // lookup instead of indexing past the end (undefined.speed crash).
    group.current.children.forEach((child, i) => {
      const ring = rings[i];
      if (!ring) return;
      child.rotation.z += ring.speed * delta;
    });
  });

  return (
    <group ref={group}>
      {rings.map((ring, i) => (
        <mesh key={i} rotation={[Math.PI / 2.1, 0, (i * Math.PI) / 5]}>
          <torusGeometry args={[ring.radius, ring.thickness, 8, 96]} />
          <meshBasicMaterial color={SIGNAL_RED} transparent opacity={ring.opacity} />
        </mesh>
      ))}
      {/* aperture blades -- a handful of thin wedges hinting at a shutter, not literal */}
      {Array.from({ length: 7 }).map((_, i) => (
        <mesh
          key={`blade-${i}`}
          rotation={[Math.PI / 2.1, 0, (i / 7) * Math.PI * 2]}
          position={[0, 0, 0]}
        >
          <planeGeometry args={[0.02, 1.1]} />
          <meshBasicMaterial color={SIGNAL_RED} transparent opacity={0.12} />
        </mesh>
      ))}
    </group>
  );
}

function randomEmberPositions(count: number): Float32Array {
  const arr = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    arr[i * 3] = (Math.random() - 0.5) * 14;
    arr[i * 3 + 1] = (Math.random() - 0.5) * 8;
    arr[i * 3 + 2] = (Math.random() - 0.5) * 6 - 2;
  }
  return arr;
}

function Embers({ count = 220 }: { count?: number }) {
  const points = useRef<THREE.Points>(null);
  // Lazy useState initializer, not useMemo: this is genuinely one-time
  // impure setup (random starting positions), and the initializer form
  // is the sanctioned escape hatch -- useMemo is for memoizing a pure
  // computation of its deps, which this isn't (rules-of-react "purity"
  // lint flags Math.random() inside useMemo, correctly).
  const [positions] = useState(() => randomEmberPositions(count));

  useFrame((state, delta) => {
    if (!points.current) return;
    points.current.rotation.y += delta * 0.01;
    const posAttr = points.current.geometry.attributes.position as THREE.BufferAttribute;
    for (let i = 0; i < count; i++) {
      const y = posAttr.getY(i) + delta * 0.06;
      posAttr.setY(i, y > 4 ? -4 : y);
    }
    posAttr.needsUpdate = true;
  });

  return (
    <points ref={points}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
      </bufferGeometry>
      <pointsMaterial color={SIGNAL_RED} size={0.03} transparent opacity={0.5} sizeAttenuation />
    </points>
  );
}

function Scene() {
  return (
    <>
      <ApertureRing />
      <Embers />
    </>
  );
}

let cachedClientSupport: boolean | null = null;

function detectWebglSupportOnce(): boolean {
  if (cachedClientSupport !== null) return cachedClientSupport;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    cachedClientSupport = false;
    return false;
  }
  try {
    const canvas = document.createElement("canvas");
    cachedClientSupport = !!(canvas.getContext("webgl") || canvas.getContext("experimental-webgl"));
  } catch {
    cachedClientSupport = false;
  }
  return cachedClientSupport;
}

// No subscription needed -- capability doesn't change after mount, so
// the subscribe callback is a no-op. useSyncExternalStore is the
// correct primitive for "a value that legitimately differs between
// server and client, read once": React reconciles server/client itself
// (getServerSnapshot -> false, matching the flat fallback) instead of
// an effect+setState cascade, which is both the lint rule's complaint
// and, more importantly, what causes a hydration flash/mismatch here.
function subscribeNoop() {
  return () => {};
}

export function NoirScene({ className }: { className?: string }) {
  const enabled = useSyncExternalStore(subscribeNoop, detectWebglSupportOnce, () => false);

  if (!enabled) return null;

  return (
    <div className={className} aria-hidden>
      <Canvas
        dpr={[1, 1.5]}
        camera={{ position: [0, 0, 6], fov: 45 }}
        gl={{ antialias: true, alpha: true }}
      >
        <Scene />
      </Canvas>
    </div>
  );
}
