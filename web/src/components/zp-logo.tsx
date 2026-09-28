"use client";

import Image from "next/image";
import { motion, useMotionValue, useReducedMotion, useSpring, useTransform } from "motion/react";
import type { PointerEvent } from "react";

// The ZP mark (2026-09-26, Mike's pick: the chunky ZP on a black disc,
// public/brand/zp_black_circle_1024.png). It is a black circle on a dark
// site, so it carries its own hairline ring + red glow or it disappears.
//
// Interactive, not animated: it tilts toward the cursor (a spring, so it
// settles rather than snaps), lifts and glows red on hover, squashes on
// press. Nothing moves until a pointer is on it, and reduced-motion users
// get the glow with no tilt.
const TILT = 18; // degrees at the disc's edge

export function ZpLogo({ size = 34, className = "" }: { size?: number; className?: string }) {
  const still = useReducedMotion();
  const px = useMotionValue(0); // -0.5 .. 0.5 across the disc
  const py = useMotionValue(0);
  const spring = { stiffness: 260, damping: 18, mass: 0.6 };
  const rotateY = useSpring(useTransform(px, [-0.5, 0.5], [-TILT, TILT]), spring);
  const rotateX = useSpring(useTransform(py, [-0.5, 0.5], [TILT, -TILT]), spring);
  // the shine follows the cursor across the face
  const shineX = useTransform(px, [-0.5, 0.5], ["20%", "80%"]);
  const shineY = useTransform(py, [-0.5, 0.5], ["20%", "80%"]);
  const shine = useTransform(
    [shineX, shineY],
    ([x, y]) => `radial-gradient(circle at ${x} ${y}, rgba(255,255,255,0.28), transparent 55%)`,
  );

  function move(e: PointerEvent<HTMLDivElement>) {
    if (still) return;
    const r = e.currentTarget.getBoundingClientRect();
    px.set((e.clientX - r.left) / r.width - 0.5);
    py.set((e.clientY - r.top) / r.height - 0.5);
  }
  function leave() {
    px.set(0);
    py.set(0);
  }

  return (
    <div
      className={`relative shrink-0 [perspective:400px] ${className}`}
      style={{ width: size, height: size }}
      onPointerMove={move}
      onPointerLeave={leave}
    >
      <motion.div
        className="zp-logo relative h-full w-full rounded-full"
        style={still ? undefined : { rotateX, rotateY, transformStyle: "preserve-3d" }}
        whileHover={{ scale: 1.12 }}
        whileTap={{ scale: 0.9 }}
        transition={{ type: "spring", stiffness: 400, damping: 15 }}
      >
        <Image
          src="/brand/zp_black_circle_1024.png"
          alt=""
          width={size * 2}
          height={size * 2}
          priority
          draggable={false}
          className="h-full w-full select-none rounded-full"
        />
        {!still && (
          <motion.span
            aria-hidden
            className="pointer-events-none absolute inset-0 rounded-full opacity-0 transition-opacity duration-300 group-hover:opacity-100"
            style={{ backgroundImage: shine }}
          />
        )}
      </motion.div>
    </div>
  );
}
